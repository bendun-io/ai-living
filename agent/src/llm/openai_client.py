from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from src.models import LLMPlan, ToolInvocation, ToolSchema


@dataclass(slots=True)
class LocalLLMClient:
    async def plan(self, messages: list[dict[str, Any]], tools: list[ToolSchema]) -> LLMPlan:
        user_message = next((message.get("content", "") for message in reversed(messages) if message.get("role") == "user"), "")
        if tools and "echo" in {tool.name for tool in tools}:
            return LLMPlan(
                kind="tool_calls",
                tool_calls=[ToolInvocation(name="echo", arguments={"message": user_message})],
            )
        return LLMPlan(kind="final", final_answer=user_message)


@dataclass(slots=True)
class OpenAIResponsesClient:
    api_key: str
    model: str
    client: AsyncOpenAI = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.client = AsyncOpenAI(api_key=self.api_key)

    async def plan(self, messages: list[dict[str, Any]], tools: list[ToolSchema]) -> LLMPlan:
        tool_payload = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema or {"type": "object", "properties": {}},
                },
            }
            for tool in tools
        ]

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tool_payload or None,
            tool_choice="auto" if tool_payload else None,
        )

        message = response.choices[0].message
        if message.tool_calls:
            tool_calls = [
                ToolInvocation(
                    name=tool_call.function.name,
                    arguments=json.loads(tool_call.function.arguments or "{}"),
                )
                for tool_call in message.tool_calls
            ]
            return LLMPlan(kind="tool_calls", tool_calls=tool_calls, response_id=response.id)

        return LLMPlan(kind="final", final_answer=message.content or "", response_id=response.id)
