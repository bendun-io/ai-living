from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.models import ToolSchema


class ToolProtocol(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    async def execute(self, arguments: dict[str, Any]) -> Any:
        ...


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, ToolProtocol] = field(default_factory=dict)

    def register(self, tool: ToolProtocol) -> None:
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> ToolProtocol:
        return self._tools[tool_name]

    def tool_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def definitions(self) -> list[ToolSchema]:
        return [
            ToolSchema(name=tool.name, description=tool.description, input_schema=tool.input_schema)
            for tool in self._tools.values()
        ]

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tools
