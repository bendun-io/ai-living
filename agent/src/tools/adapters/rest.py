from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class RestTool:
    name: str
    description: str
    endpoint: str
    input_schema: dict[str, Any]
    method: str = "POST"

    async def execute(self, arguments: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(self.method, self.endpoint, json=arguments)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return {"text": response.text}
