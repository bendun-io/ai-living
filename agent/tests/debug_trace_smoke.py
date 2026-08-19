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
from src.models import AgentRunRequest
from src.skills.library import SkillLibrary
from src.tools.adapters.local import build_local_tools
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


def test_agent_response_contains_debug_trace() -> None:
    async def run_case() -> None:
        skill_library = SkillLibrary.default()
        registry = ToolRegistry()
        for tool in build_local_tools(skill_library):
            registry.register(tool)

        service = AgentService(
            llm_client=LocalLLMClient(),
            tool_registry=registry,
            tool_executor=ToolExecutor(registry),
            memory_store=MemoryStore(),
            callback_client=CallbackClient(url=None),
            skill_library=skill_library,
            max_iterations=1,
        )

        response = await service.run(
            AgentRunRequest(
                conversationId="debug-trace-smoke",
                user="tester",
                message="echo hello",
                attachments=[],
            )
        )

        assert isinstance(response.debug.skillsRead, list)
        assert response.debug.skillsRead
        assert isinstance(response.debug.toolsUsed, list)
        assert response.debug.toolsUsed
        assert response.debug.toolsUsed[0].tool == "echo"
        assert response.debug.toolsUsed[0].arguments == {"message": "echo hello"}

    asyncio.run(run_case())
