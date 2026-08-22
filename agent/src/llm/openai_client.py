from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from src.models import LLMPlan, ToolInvocation, ToolSchema


@dataclass(slots=True)
class LocalLLMClient:
    async def plan(self, messages: list[dict[str, Any]], tools: list[ToolSchema]) -> LLMPlan:
        user_message = next((message.get("content", "") for message in reversed(messages) if message.get("role") == "user"), "")
        tool_names = {tool.name for tool in tools}

        list_plan = _plan_list_tool_call(messages, user_message, tool_names)
        if list_plan is not None:
            return list_plan

        if tools and "echo" in tool_names:
            return LLMPlan(
                kind="tool_calls",
                tool_calls=[ToolInvocation(name="echo", arguments={"message": user_message})],
            )
        return LLMPlan(kind="final", final_answer=user_message)


UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


def _plan_list_tool_call(messages: list[dict[str, Any]], user_message: str, tool_names: set[str]) -> LLMPlan | None:
    text = user_message.strip()
    lower = text.lower()

    if not any(name.startswith("lists_") or name.startswith("items_") for name in tool_names):
        return None

    if _is_search_lists_intent(lower) and "lists_search" in tool_names:
        query = _extract_query_phrase(text)
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="lists_search", arguments=_search_args(query))])

    if _is_create_list_intent(lower) and "lists_create" in tool_names:
        name = _extract_list_name(text)
        if not name:
            return LLMPlan(kind="final", final_answer="Please provide the list name you want me to create.")
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="lists_create", arguments={"name": name, "actor": "agent"})])

    if _is_get_list_intent(lower) and "lists_get" in tool_names:
        list_id = _extract_uuid(text)
        if not list_id:
            return LLMPlan(kind="final", final_answer="Please provide the list id so I can fetch it.")
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="lists_get", arguments={"id": list_id})])

    if _is_update_list_intent(lower) and "lists_update" in tool_names:
        list_id = _extract_uuid(text)
        if not list_id:
            return LLMPlan(kind="final", final_answer="Please provide the list id to update.")
        name = _extract_named_value(text, "name")
        description = _extract_named_value(text, "description")
        if not name and not description:
            return LLMPlan(kind="final", final_answer="Please provide at least one field to update, like name or description.")
        arguments: dict[str, Any] = {"id": list_id, "actor": "agent"}
        if name:
            arguments["name"] = name
        if description:
            arguments["description"] = description
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="lists_update", arguments=arguments)])

    if _is_delete_list_intent(lower) and "lists_delete" in tool_names:
        list_id = _extract_uuid(text)
        if not list_id:
            return LLMPlan(kind="final", final_answer="Please provide the list id to delete.")
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="lists_delete", arguments={"id": list_id, "actor": "agent"})])

    if _is_add_item_intent(lower) and "items_create" in tool_names:
        title = _extract_item_title(text)
        if not title:
            return LLMPlan(kind="final", final_answer="Please provide the item title to add.")

        list_id = _extract_list_id(text)
        if not list_id:
            list_name = _extract_list_name_for_item(text)
            searched_list_id = _list_id_from_latest_search(messages)
            if searched_list_id:
                list_id = searched_list_id
            elif list_name and "lists_search" in tool_names:
                return LLMPlan(
                    kind="tool_calls",
                    tool_calls=[ToolInvocation(name="lists_search", arguments=_search_args(list_name, limit=5))],
                )
            else:
                return LLMPlan(
                    kind="final",
                    final_answer="Please provide a list id or a list name after 'to list' so I can add the item.",
                )

        arguments = {"list_id": list_id, "title": title, "actor": "agent"}
        status = _extract_named_value(text, "status")
        notes = _extract_named_value(text, "notes") or _extract_named_value(text, "note")
        if status:
            arguments["status"] = status
        if notes:
            arguments["notes"] = notes
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="items_create", arguments=arguments)])

    if _is_search_items_intent(lower) and "items_search" in tool_names:
        query = _extract_query_phrase(text)
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="items_search", arguments=_search_args(query))])

    if _is_get_item_intent(lower) and "items_get" in tool_names:
        item_id = _extract_uuid(text)
        if not item_id:
            return LLMPlan(kind="final", final_answer="Please provide the item id so I can fetch it.")
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="items_get", arguments={"id": item_id})])

    if _is_update_item_intent(lower) and "items_update" in tool_names:
        item_id = _extract_uuid(text)
        if not item_id:
            return LLMPlan(kind="final", final_answer="Please provide the item id to update.")
        title = _extract_named_value(text, "title")
        status = _extract_named_value(text, "status")
        notes = _extract_named_value(text, "notes") or _extract_named_value(text, "note")
        if not any([title, status, notes]):
            return LLMPlan(kind="final", final_answer="Please provide at least one field to update, like title, status, or notes.")
        arguments = {"id": item_id, "actor": "agent"}
        if title:
            arguments["title"] = title
        if status:
            arguments["status"] = status
        if notes:
            arguments["notes"] = notes
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="items_update", arguments=arguments)])

    if _is_delete_item_intent(lower) and "items_delete" in tool_names:
        item_id = _extract_uuid(text)
        if not item_id:
            return LLMPlan(kind="final", final_answer="Please provide the item id to delete.")
        return LLMPlan(kind="tool_calls", tool_calls=[ToolInvocation(name="items_delete", arguments={"id": item_id, "actor": "agent"})])

    return None


def _is_search_lists_intent(text: str) -> bool:
    if "list" not in text:
        return False
    return any(token in text for token in ["search", "find", "show lists", "list all lists"])


def _is_create_list_intent(text: str) -> bool:
    return "list" in text and any(token in text for token in ["create", "new", "add"])


def _is_get_list_intent(text: str) -> bool:
    return "list" in text and any(token in text for token in ["get", "show details", "details"])


def _is_update_list_intent(text: str) -> bool:
    return "list" in text and any(token in text for token in ["update", "rename", "edit"])


def _is_delete_list_intent(text: str) -> bool:
    return "list" in text and any(token in text for token in ["delete", "remove"])


def _is_add_item_intent(text: str) -> bool:
    return "item" in text and any(token in text for token in ["create", "add", "new"])


def _is_search_items_intent(text: str) -> bool:
    if "item" not in text:
        return False
    return any(token in text for token in ["search", "find", "show items", "list all items"])


def _is_get_item_intent(text: str) -> bool:
    return "item" in text and any(token in text for token in ["get", "details", "show"])


def _is_update_item_intent(text: str) -> bool:
    return "item" in text and any(token in text for token in ["update", "edit"])


def _is_delete_item_intent(text: str) -> bool:
    return "item" in text and any(token in text for token in ["delete", "remove"])


def _extract_quoted_text(text: str) -> str | None:
    match = re.search(r'"([^"]+)"', text)
    if match:
        return match.group(1).strip()
    return None


def _extract_query_phrase(text: str) -> str | None:
    quoted = _extract_quoted_text(text)
    if quoted:
        return quoted
    match = re.search(r"\b(?:for|about|named)\s+(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip(" .")
    return value or None


def _extract_list_name(text: str) -> str | None:
    quoted = _extract_quoted_text(text)
    if quoted:
        return quoted
    match = re.search(r"\b(?:list\s+named|list\s+called|create\s+list|new\s+list)\s+(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None
    name = match.group(1).strip(" .")
    name = re.split(r"\bdescription\b", name, flags=re.IGNORECASE)[0].strip()
    return name or None


def _extract_list_name_for_item(text: str) -> str | None:
    match = re.search(r"\bto\s+list\s+(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip(" .")
    quoted = _extract_quoted_text(value)
    if quoted:
        return quoted
    return value or None


def _extract_item_title(text: str) -> str | None:
    quoted = _extract_quoted_text(text)
    if quoted:
        return quoted
    match = re.search(r"\b(?:add|create|new)\s+item\s+(.+?)(?:\s+to\s+list\b|\s+status\b|\s+note\b|\s+notes\b|$)", text, flags=re.IGNORECASE)
    if not match:
        return None
    title = match.group(1).strip(" .")
    return title or None


def _extract_uuid(text: str) -> str | None:
    match = UUID_PATTERN.search(text)
    if not match:
        return None
    return match.group(0)


def _extract_list_id(text: str) -> str | None:
    match = re.search(
        r"\blist(?:\s+id)?\s+([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return _extract_uuid(text)


def _extract_named_value(text: str, key: str) -> str | None:
    quoted = None
    key_match = re.search(rf"\b{re.escape(key)}\b", text, flags=re.IGNORECASE)
    if key_match:
        after = text[key_match.end():].strip()
        quoted = _extract_quoted_text(after)
        if quoted:
            return quoted
        plain = re.split(r"\b(?:name|description|status|title|notes|note|to\s+list)\b", after, maxsplit=1, flags=re.IGNORECASE)[0].strip(" :,")
        if plain:
            return plain
    return None


def _search_args(query: str | None, limit: int = 20) -> dict[str, Any]:
    arguments: dict[str, Any] = {"include_deleted": False, "limit": limit, "offset": 0}
    if query:
        arguments["query"] = query
    return arguments


def _list_id_from_latest_search(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue

        if payload.get("name") != "lists_search" or not payload.get("ok"):
            continue

        output = payload.get("output")
        if not isinstance(output, dict):
            continue

        lists = output.get("lists")
        if isinstance(lists, list) and lists and isinstance(lists[0], dict):
            list_id = lists[0].get("id")
            if isinstance(list_id, str) and list_id:
                return list_id
    return None


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
