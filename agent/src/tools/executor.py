from __future__ import annotations

import logging
from dataclasses import dataclass

from src.models import ToolExecutionRecord, ToolInvocation, ToolResult
from .registry import ToolRegistry


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ToolExecutor:
    registry: ToolRegistry

    async def execute(self, invocation: ToolInvocation) -> ToolExecutionRecord:
        tool = self.registry.find(invocation.name)
        if tool is None:
            result = self._unknown_tool_result(invocation.name)
        else:
            try:
                output = await tool.execute(invocation.arguments)
                result = ToolResult(name=invocation.name, ok=True, output=output)
            except Exception as exc:  # noqa: BLE001
                result = ToolResult(name=invocation.name, ok=False, error=str(exc))
        return ToolExecutionRecord(tool=invocation.name, arguments=invocation.arguments, result=result)

    def _unknown_tool_result(self, tool_name: str) -> ToolResult:
        """Turn a hallucinated or stale tool name into a correctable error.

        Returning it as a failed ToolResult keeps the run alive and hands the planner the
        list of real tool names, so it can retry with a valid one on the next iteration
        instead of taking down the whole request with a KeyError.
        """
        available = self.registry.tool_names()
        logger.warning(
            "Planner requested unknown tool %r; %s tool(s) registered",
            tool_name,
            len(available),
        )
        known = ", ".join(available) if available else "none"
        return ToolResult(
            name=tool_name,
            ok=False,
            error=f"Unknown tool '{tool_name}'. Available tools: {known}.",
        )
