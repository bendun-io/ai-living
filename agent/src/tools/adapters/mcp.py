from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MCPToolAdapter:
    server_url: str
    discovered_tools: list[dict[str, Any]] = field(default_factory=list)

    async def discover_tools(self) -> list[dict[str, Any]]:
        return self.discovered_tools

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "serverUrl": self.server_url,
            "tool": tool_name,
            "arguments": arguments,
            "status": "not_implemented",
        }
