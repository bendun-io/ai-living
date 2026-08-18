from __future__ import annotations

from dataclasses import dataclass

from src.models import ToolExecutionRecord, ToolInvocation, ToolResult
from .registry import ToolRegistry


@dataclass(slots=True)
class ToolExecutor:
    registry: ToolRegistry

    async def execute(self, invocation: ToolInvocation) -> ToolExecutionRecord:
        tool = self.registry.get(invocation.name)
        try:
            output = await tool.execute(invocation.arguments)
            result = ToolResult(name=invocation.name, ok=True, output=output)
        except Exception as exc:  # noqa: BLE001
            result = ToolResult(name=invocation.name, ok=False, error=str(exc))
        return ToolExecutionRecord(tool=invocation.name, arguments=invocation.arguments, result=result)
