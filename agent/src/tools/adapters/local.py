from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EchoTool:
    name: str = "echo"
    description: str = "Return the provided arguments for local testing."
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        }
    )

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"received": arguments}


def build_local_tools() -> list[EchoTool]:
    return [EchoTool()]
