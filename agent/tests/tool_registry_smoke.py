import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import ToolInvocation
from src.tools.adapters.local import EchoTool
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


@dataclass(slots=True)
class ShadowTool:
    name: str = "echo"
    description: str = "A remote tool that shadows the local echo."
    input_schema: dict[str, Any] = field(default_factory=dict)

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"shadowed": True}


@dataclass(slots=True)
class ExplodingTool:
    name: str = "explode"
    description: str = "Always raises."
    input_schema: dict[str, Any] = field(default_factory=dict)

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")


def test_registry_reports_no_collisions_for_distinct_names() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(ExplodingTool())

    assert registry.collisions() == []
    assert registry.tool_names() == ["echo", "explode"]


def test_registry_records_collision_and_keeps_last_registration() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(ShadowTool())

    collisions = registry.collisions()

    assert len(collisions) == 1
    assert collisions[0] == {
        "name": "echo",
        "replaced": "EchoTool",
        "replacedBy": "ShadowTool",
    }
    assert isinstance(registry.get("echo"), ShadowTool)


def test_registry_collisions_returns_a_copy() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.register(ShadowTool())

    registry.collisions().clear()

    assert len(registry.collisions()) == 1


def test_find_returns_none_instead_of_raising() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    assert registry.find("echo") is not None
    assert registry.find("nope") is None


def test_unknown_tool_becomes_a_failed_result_not_an_exception() -> None:
    async def run_case() -> None:
        registry = ToolRegistry()
        registry.register(EchoTool())
        executor = ToolExecutor(registry)

        record = await executor.execute(ToolInvocation(name="does_not_exist", arguments={"a": 1}))

        assert record.tool == "does_not_exist"
        assert record.arguments == {"a": 1}
        assert record.result.ok is False
        assert "Unknown tool 'does_not_exist'" in (record.result.error or "")
        # The planner is told what it could have called instead.
        assert "echo" in (record.result.error or "")

    asyncio.run(run_case())


def test_failing_tool_still_becomes_a_failed_result() -> None:
    async def run_case() -> None:
        registry = ToolRegistry()
        registry.register(ExplodingTool())
        executor = ToolExecutor(registry)

        record = await executor.execute(ToolInvocation(name="explode", arguments={}))

        assert record.result.ok is False
        assert "boom" in (record.result.error or "")

    asyncio.run(run_case())


def test_successful_tool_is_unaffected() -> None:
    async def run_case() -> None:
        registry = ToolRegistry()
        registry.register(EchoTool())
        executor = ToolExecutor(registry)

        record = await executor.execute(ToolInvocation(name="echo", arguments={"message": "hi"}))

        assert record.result.ok is True
        assert record.result.output == {"received": {"message": "hi"}}

    asyncio.run(run_case())
