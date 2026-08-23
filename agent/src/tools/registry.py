from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.models import ToolSchema


logger = logging.getLogger(__name__)


class ToolProtocol(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    async def execute(self, arguments: dict[str, Any]) -> Any:
        ...


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, ToolProtocol] = field(default_factory=dict)
    _collisions: list[dict[str, str]] = field(default_factory=list)

    def register(self, tool: ToolProtocol) -> None:
        """Register a tool, last write wins, but never silently.

        Discovered tools arrive from remote services, so a name clash can quietly
        replace a local tool with a remote one. The replacement still happens — refusing
        it would leave the registry in a state that depends on discovery order — but it is
        logged and surfaced through the health snapshot so it cannot go unnoticed.
        """
        existing = self._tools.get(tool.name)
        if existing is not None:
            collision = {
                "name": tool.name,
                "replaced": type(existing).__name__,
                "replacedBy": type(tool).__name__,
            }
            self._collisions.append(collision)
            logger.warning(
                "Tool name collision: %r registered by %s replaces the existing %s",
                tool.name,
                collision["replacedBy"],
                collision["replaced"],
            )

        self._tools[tool.name] = tool

    def unregister(self, tool_name: str) -> bool:
        """Drop a tool, reporting whether it was there.

        Needed by sources that rediscover periodically: without it, a tool the remote
        server has withdrawn would stay callable until the next process restart.
        """
        return self._tools.pop(tool_name, None) is not None

    def get(self, tool_name: str) -> ToolProtocol:
        return self._tools[tool_name]

    def find(self, tool_name: str) -> ToolProtocol | None:
        """Look up a tool without raising, for callers that handle absence themselves."""
        return self._tools.get(tool_name)

    def collisions(self) -> list[dict[str, str]]:
        return list(self._collisions)

    def tool_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def definitions(self) -> list[ToolSchema]:
        return [
            ToolSchema(name=tool.name, description=tool.description, input_schema=tool.input_schema)
            for tool in self._tools.values()
        ]

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tools
