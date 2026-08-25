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
    http_client: httpx.AsyncClient
    method: str = "POST"

    async def execute(self, arguments: dict[str, Any]) -> Any:
        response = await self.http_client.request(self.method, self.endpoint, json=arguments)
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return {"text": response.text}


async def fetch_rest_tool_definitions(base_url: str, http_client: httpx.AsyncClient) -> list[RestTool]:
    normalized_base = base_url.rstrip("/")
    discovery_url = f"{normalized_base}/agent/tool-definitions"

    response = await http_client.get(discovery_url)
    response.raise_for_status()
    payload = response.json()

    tools: list[RestTool] = []
    for item in payload.get("tools", []):
        name = str(item.get("name", "")).strip()
        endpoint = str(item.get("endpoint", "")).strip()
        if not name or not endpoint:
            continue

        method = str(item.get("method", "POST")).upper()
        description = str(item.get("description", "")).strip()
        input_schema = item.get("input_schema", {})
        if not isinstance(input_schema, dict):
            input_schema = {}

        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            target_endpoint = endpoint
        else:
            target_endpoint = f"{normalized_base}{endpoint if endpoint.startswith('/') else '/' + endpoint}"

        tools.append(
            RestTool(
                name=name,
                description=description,
                endpoint=target_endpoint,
                input_schema=input_schema,
                http_client=http_client,
                method=method,
            )
        )

    return tools
