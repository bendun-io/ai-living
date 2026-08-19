from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.callbacks.callback import CallbackClient
from src.llm.openai_client import LocalLLMClient, OpenAIResponsesClient
from src.memory.memory import MemoryStore
from src.models import AgentRunRequest, AgentRunResponse, CallbackPayload, DebugTrace, ToolExecutionRecord, ToolInvocation, ToolUsageTrace
from src.skills.library import SkillLibrary
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

from .planner import build_prompt_bundle


@dataclass(slots=True)
class AgentService:
    llm_client: Any
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    memory_store: MemoryStore
    callback_client: CallbackClient
    skill_library: SkillLibrary | None = None
    max_iterations: int = 5

    async def run(self, request: AgentRunRequest) -> AgentRunResponse:
        memory = self._chat_safe_memory(await self.memory_store.load(request.conversationId))
        prompt_bundle = build_prompt_bundle(request, self.tool_registry.definitions(), self.skill_library)
        messages = [
            {"role": "system", "content": prompt_bundle.system_prompt},
            *memory,
            {"role": "user", "content": prompt_bundle.user_prompt},
        ]
        tool_log: list[ToolExecutionRecord] = []
        tools_used: list[ToolUsageTrace] = []
        result_text = request.message

        for _ in range(self.max_iterations):
            plan = await self.llm_client.plan(messages, self.tool_registry.definitions())
            if plan.kind == "final":
                result_text = plan.final_answer or result_text
                break

            assistant_message = self._build_assistant_tool_message(plan.tool_calls)
            messages.append(assistant_message)

            for invocation in plan.tool_calls:
                tools_used.append(ToolUsageTrace(tool=invocation.name, arguments=invocation.arguments))
                record = await self.tool_executor.execute(invocation)
                tool_log.append(record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": invocation.call_id or invocation.name,
                        "content": record.result.model_dump_json(),
                    }
                )

        skills_read = self.skill_library.skill_names() if self.skill_library is not None else []
        debug_trace = DebugTrace(skillsRead=skills_read, toolsUsed=tools_used)

        response = AgentRunResponse(
            conversationId=request.conversationId,
            result=result_text,
            toolLog=tool_log,
            debug=debug_trace,
            metadata=request.metadata,
        )
        await self.memory_store.append(
            request.conversationId,
            {"role": "user", "content": prompt_bundle.user_prompt},
        )
        await self.memory_store.append(
            request.conversationId,
            {"role": "assistant", "content": result_text},
        )
        await self.callback_client.send(CallbackPayload(**response.model_dump()))
        return response

    def _chat_safe_memory(self, raw_memory: list[dict[str, Any]]) -> list[dict[str, str]]:
        safe_roles = {"system", "user", "assistant"}
        safe_messages: list[dict[str, str]] = []

        for item in raw_memory:
            role = item.get("role")
            content = item.get("content")
            if role in safe_roles and isinstance(content, str):
                safe_messages.append({"role": role, "content": content})

        return safe_messages

    def _build_assistant_tool_message(self, invocations: list[ToolInvocation]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": invocation.call_id or invocation.name,
                    "type": "function",
                    "function": {
                        "name": invocation.name,
                        "arguments": invocation.model_dump_json(exclude={"call_id"}),
                    },
                }
                for invocation in invocations
            ],
        }
