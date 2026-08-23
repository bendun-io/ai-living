import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.executor import AgentService
from src.callbacks.callback import CallbackClient
from src.llm.openai_client import LocalLLMClient
from src.memory.memory import MemoryStore
from src.models import AgentRunRequest, LLMPlan, ToolInvocation
from src.skills.library import SkillLibrary
from src.tools.adapters.local import build_local_tools
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


class ScriptedLLMClient:
    """Replays a fixed list of plans so the loop can be exercised without a provider."""

    def __init__(self, plans: list[LLMPlan]) -> None:
        self._plans = list(plans)

    async def plan(self, messages, tools) -> LLMPlan:
        if self._plans:
            return self._plans.pop(0)
        return LLMPlan(kind="final", final_answer="done")


def _build_service(llm_client, max_iterations: int = 1) -> AgentService:
    skill_library = SkillLibrary.default()
    registry = ToolRegistry()
    for tool in build_local_tools(skill_library):
        registry.register(tool)

    return AgentService(
        llm_client=llm_client,
        tool_registry=registry,
        tool_executor=ToolExecutor(registry),
        memory_store=MemoryStore(),
        callback_client=CallbackClient(url=None),
        skill_library=skill_library,
        max_iterations=max_iterations,
    )


def test_agent_response_contains_debug_trace() -> None:
    async def run_case() -> None:
        service = _build_service(LocalLLMClient())

        response = await service.run(
            AgentRunRequest(
                conversationId="debug-trace-smoke",
                user="tester",
                message="echo hello",
                attachments=[],
            )
        )

        assert isinstance(response.debug.toolsUsed, list)
        assert response.debug.toolsUsed
        assert response.debug.toolsUsed[0].tool == "echo"
        assert response.debug.toolsUsed[0].arguments == {"message": "echo hello"}

    asyncio.run(run_case())


def test_skills_read_is_empty_when_no_skill_lookup_happens() -> None:
    async def run_case() -> None:
        service = _build_service(LocalLLMClient())

        response = await service.run(
            AgentRunRequest(
                conversationId="skills-read-none",
                user="tester",
                message="echo hello",
                attachments=[],
            )
        )

        assert response.debug.toolsUsed[0].tool == "echo"
        assert response.debug.skillsRead == []

    asyncio.run(run_case())


def test_skills_read_lists_only_consulted_skills() -> None:
    async def run_case() -> None:
        service = _build_service(
            ScriptedLLMClient(
                [
                    LLMPlan(
                        kind="tool_calls",
                        tool_calls=[
                            ToolInvocation(name="search_skills", arguments={"query": "calendar"})
                        ],
                    ),
                    LLMPlan(kind="final", final_answer="checked the calendar skill"),
                ]
            ),
            max_iterations=3,
        )

        response = await service.run(
            AgentRunRequest(
                conversationId="skills-read-one",
                user="tester",
                message="when am I free?",
                attachments=[],
            )
        )

        library_names = SkillLibrary.default().skill_names()

        assert response.debug.skillsRead == ["calendar_lookup"]
        assert len(response.debug.skillsRead) < len(library_names)

    asyncio.run(run_case())


def test_skills_read_deduplicates_across_repeated_lookups() -> None:
    async def run_case() -> None:
        service = _build_service(
            ScriptedLLMClient(
                [
                    LLMPlan(
                        kind="tool_calls",
                        tool_calls=[
                            ToolInvocation(name="search_skills", arguments={"query": "calendar"}),
                            ToolInvocation(name="search_skills", arguments={"query": "joke"}),
                        ],
                    ),
                    LLMPlan(
                        kind="tool_calls",
                        tool_calls=[
                            ToolInvocation(name="search_skills", arguments={"query": "calendar"})
                        ],
                    ),
                    LLMPlan(kind="final", final_answer="done"),
                ]
            ),
            max_iterations=3,
        )

        response = await service.run(
            AgentRunRequest(
                conversationId="skills-read-dedup",
                user="tester",
                message="tell me a joke about my calendar",
                attachments=[],
            )
        )

        assert response.debug.skillsRead == ["calendar_lookup", "joke_teller"]

    asyncio.run(run_case())
