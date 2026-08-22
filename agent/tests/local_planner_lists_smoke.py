import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.llm.openai_client import LocalLLMClient
from src.models import ToolSchema


def _tools(*names: str) -> list[ToolSchema]:
    return [ToolSchema(name=name, description=name, input_schema={"type": "object", "properties": {}}) for name in names]


def _run_plan(messages: list[dict[str, object]], tool_names: tuple[str, ...]):
    client = LocalLLMClient()
    return asyncio.run(client.plan(messages, _tools(*tool_names)))


def test_local_planner_routes_list_search() -> None:
    plan = _run_plan(
        [{"role": "user", "content": 'search lists for "project"'}],
        ("echo", "lists_search"),
    )

    assert plan.kind == "tool_calls"
    assert len(plan.tool_calls) == 1
    assert plan.tool_calls[0].name == "lists_search"
    assert plan.tool_calls[0].arguments.get("query") == "project"


def test_local_planner_routes_create_list() -> None:
    plan = _run_plan(
        [{"role": "user", "content": 'create list "Groceries"'}],
        ("echo", "lists_create"),
    )

    assert plan.kind == "tool_calls"
    assert plan.tool_calls[0].name == "lists_create"
    assert plan.tool_calls[0].arguments["name"] == "Groceries"


def test_local_planner_add_item_with_list_id() -> None:
    list_id = "11111111-1111-4111-8111-111111111111"
    plan = _run_plan(
        [{"role": "user", "content": f'add item "Milk" to list {list_id} status open'}],
        ("echo", "items_create"),
    )

    assert plan.kind == "tool_calls"
    assert plan.tool_calls[0].name == "items_create"
    assert plan.tool_calls[0].arguments["list_id"] == list_id
    assert plan.tool_calls[0].arguments["title"] == "Milk"


def test_local_planner_add_item_after_list_search() -> None:
    list_id = "22222222-2222-4222-8222-222222222222"
    tool_message = {
        "role": "tool",
        "content": json.dumps(
            {
                "name": "lists_search",
                "ok": True,
                "output": {"lists": [{"id": list_id, "name": "Groceries"}]},
            }
        ),
    }
    plan = _run_plan(
        [
            {"role": "user", "content": 'add item "Bread" to list Groceries'},
            tool_message,
        ],
        ("echo", "lists_search", "items_create"),
    )

    assert plan.kind == "tool_calls"
    assert plan.tool_calls[0].name == "items_create"
    assert plan.tool_calls[0].arguments["list_id"] == list_id
    assert plan.tool_calls[0].arguments["title"] == "Bread"


def test_local_planner_requests_missing_item_context() -> None:
    plan = _run_plan(
        [{"role": "user", "content": 'add item "Bread"'}],
        ("echo", "items_create"),
    )

    assert plan.kind == "final"
    assert "list id" in (plan.final_answer or "").lower()
