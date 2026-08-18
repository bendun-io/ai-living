from __future__ import annotations

from dataclasses import dataclass

from src.models import AgentRunRequest, ToolSchema
from .prompts import build_system_prompt, build_tool_context, build_user_prompt


@dataclass(slots=True)
class PromptBundle:
    system_prompt: str
    user_prompt: str
    tool_context: str


def build_prompt_bundle(request: AgentRunRequest, tools: list[ToolSchema]) -> PromptBundle:
    return PromptBundle(
        system_prompt=build_system_prompt(),
        user_prompt=build_user_prompt(request),
        tool_context=build_tool_context(tools),
    )
