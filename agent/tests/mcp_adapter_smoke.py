import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.agent.agent as agent_module
from src.agent.agent import AgentRuntime
from src.config import Settings
from src.models import ToolInvocation
from src.tools.adapters.local import EchoTool
from src.tools.adapters.mcp import (
    MCPServerConfig,
    MCPTool,
    MCPToolAdapter,
    build_mcp_tools,
    default_prefix,
    load_mcp_server_configs,
    parse_mcp_server_configs,
)
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


class FakeAdapter:
    """Stands in for a live MCP server so the mapping can be tested offline."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, remote_name: str, arguments: dict):
        self.calls.append((remote_name, arguments))
        return {"called": remote_name}


class FakeContentBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class FakeToolResult:
    def __init__(self, text: str, is_error: bool = False, structured=None) -> None:
        self.content = [FakeContentBlock(text)]
        self.isError = is_error
        self.structuredContent = structured


def _config(name: str = "homeassistant", prefix: str = "ha_") -> MCPServerConfig:
    return MCPServerConfig(name=name, url="http://ha.local:8123/api/mcp", prefix=prefix)


def test_prefix_defaults_to_the_server_name() -> None:
    assert default_prefix("homeassistant") == "homeassistant_"
    assert default_prefix("Home Assistant") == "home_assistant_"
    assert default_prefix("") == ""


def test_config_entries_are_parsed_with_defaults() -> None:
    configs = parse_mcp_server_configs(
        {
            "servers": [
                {"name": "homeassistant", "url": "http://ha.local:8123/api/mcp"},
                {"name": "explicit", "url": "http://x/mcp", "prefix": "", "transport": "sse", "timeoutSeconds": 5},
            ]
        }
    )

    assert [config.name for config in configs] == ["homeassistant", "explicit"]
    assert configs[0].prefix == "homeassistant_"
    assert configs[0].transport == "streamable_http"
    assert configs[0].timeout_seconds == 30.0
    assert configs[1].prefix == ""
    assert configs[1].transport == "sse"
    assert configs[1].timeout_seconds == 5.0


def test_unusable_entries_are_skipped_rather_than_fatal() -> None:
    configs = parse_mcp_server_configs(
        {
            "servers": [
                {"name": "no-url"},
                {"url": "http://no-name/mcp"},
                {"name": "disabled", "url": "http://x/mcp", "enabled": False},
                "not-an-object",
                {"name": "good", "url": "http://good/mcp"},
            ]
        }
    )

    assert [config.name for config in configs] == ["good"]


def test_tokens_and_urls_come_from_the_environment() -> None:
    os.environ["MCP_SMOKE_TOKEN"] = "secret-token"
    os.environ["MCP_SMOKE_HOST"] = "ha.internal"
    try:
        configs = parse_mcp_server_configs(
            {
                "servers": [
                    {
                        "name": "homeassistant",
                        "url": "http://${MCP_SMOKE_HOST}:8123/api/mcp",
                        "tokenEnv": "MCP_SMOKE_TOKEN",
                        "headers": {"X-Trace": "agent"},
                    }
                ]
            }
        )
    finally:
        del os.environ["MCP_SMOKE_TOKEN"]
        del os.environ["MCP_SMOKE_HOST"]

    config = configs[0]

    assert config.url == "http://ha.internal:8123/api/mcp"
    assert config.token == "secret-token"
    assert config.request_headers() == {"X-Trace": "agent", "Authorization": "Bearer secret-token"}


def test_missing_token_env_leaves_the_server_unauthenticated() -> None:
    os.environ.pop("MCP_SMOKE_ABSENT", None)

    configs = parse_mcp_server_configs(
        {"servers": [{"name": "ha", "url": "http://x/mcp", "tokenEnv": "MCP_SMOKE_ABSENT"}]}
    )

    assert configs[0].token is None
    assert configs[0].request_headers() == {}


def test_shipped_config_file_parses() -> None:
    configs = load_mcp_server_configs(str(ROOT / "config" / "mcp-servers.json"))

    # The shipped Home Assistant entry is disabled, so nothing is enabled by default.
    assert configs == []


def test_discovered_tools_are_prefixed_but_called_by_their_remote_name() -> None:
    async def run_case() -> None:
        adapter = FakeAdapter(_config())
        tools = build_mcp_tools(adapter, [{"name": "HassTurnOn", "description": "on", "input_schema": {"type": "object"}}])

        assert [tool.name for tool in tools] == ["ha_HassTurnOn"]
        assert tools[0].remote_name == "HassTurnOn"

        await tools[0].execute({"name": "kitchen"})

        assert adapter.calls == [("HassTurnOn", {"name": "kitchen"})]

    asyncio.run(run_case())


def test_nameless_tools_are_skipped() -> None:
    tools = build_mcp_tools(FakeAdapter(_config()), [{"description": "no name"}, {"name": "ok"}])

    assert [tool.name for tool in tools] == ["ha_ok"]


def test_tool_results_are_flattened_and_errors_raise() -> None:
    adapter = MCPToolAdapter(config=_config())

    assert adapter._unwrap("t", FakeToolResult("living room is on")) == "living room is on"
    assert adapter._unwrap("t", FakeToolResult("ignored", structured={"state": "on"})) == {"state": "on"}

    try:
        adapter._unwrap("t", FakeToolResult("entity not exposed", is_error=True))
    except RuntimeError as exc:
        assert "entity not exposed" in str(exc)
    else:
        raise AssertionError("an MCP tool error must raise so ToolExecutor records it")


def test_failed_mcp_call_becomes_a_recoverable_tool_result() -> None:
    async def run_case() -> None:
        class ExplodingAdapter(FakeAdapter):
            async def call_tool(self, remote_name, arguments):
                raise RuntimeError("connection refused")

        registry = ToolRegistry()
        for tool in build_mcp_tools(ExplodingAdapter(_config()), [{"name": "HassTurnOn"}]):
            registry.register(tool)

        record = await ToolExecutor(registry).execute(ToolInvocation(name="ha_HassTurnOn", arguments={}))

        assert record.result.ok is False
        assert "connection refused" in (record.result.error or "")

    asyncio.run(run_case())


def test_unregister_removes_a_tool() -> None:
    registry = ToolRegistry()
    registry.register(EchoTool())

    assert registry.unregister("echo") is True
    assert registry.unregister("echo") is False
    assert registry.tool_names() == []


def _runtime_with_servers(tmp_config: Path, servers: list[dict]) -> AgentRuntime:
    tmp_config.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    settings = Settings(
        enable_mcp=True,
        mcp_servers_file=str(tmp_config),
        mcp_refresh_interval_seconds=0,  # no background loop inside the smoke tests
    )
    return AgentRuntime(settings=settings)


def test_refresh_swaps_tools_and_drops_withdrawn_ones() -> None:
    config_file = Path(os.environ.get("TEMP", "/tmp")) / "mcp-refresh-smoke.json"

    async def run_case() -> None:
        runtime = _runtime_with_servers(config_file, [{"name": "ha", "url": "http://ha/mcp", "prefix": "ha_"}])
        await runtime.initialize()

        assert "ha_first" in (runtime.tool_registry.tool_names())

        _install_discovery(lambda config: build_mcp_tools(FakeAdapter(config), [{"name": "second"}]))
        await runtime.refresh_mcp_tools()

        names = runtime.tool_registry.tool_names()
        assert "ha_second" in names
        assert "ha_first" not in names
        assert "echo" in names  # local tools survive a refresh
        assert runtime.health_snapshot()["mcpServers"][0]["tools"] == 1

    original = agent_module.discover_mcp_tools
    _install_discovery(lambda config: build_mcp_tools(FakeAdapter(config), [{"name": "first"}]))
    try:
        asyncio.run(run_case())
    finally:
        agent_module.discover_mcp_tools = original
        config_file.unlink(missing_ok=True)


def test_a_failing_server_keeps_its_previous_tools() -> None:
    tmp_path = Path(os.environ.get("TEMP", "/tmp"))
    config_file = tmp_path / "mcp-failure-smoke.json"

    async def run_case() -> None:
        runtime = _runtime_with_servers(config_file, [{"name": "ha", "url": "http://ha/mcp", "prefix": "ha_"}])
        await runtime.initialize()

        async def failing_discovery(config):
            raise RuntimeError("server unreachable")

        agent_module.discover_mcp_tools = failing_discovery
        await runtime.refresh_mcp_tools()

        assert "ha_first" in runtime.tool_registry.tool_names()
        status = runtime.health_snapshot()["mcpServers"][0]
        assert status["error"] == "server unreachable"
        assert status["tools"] == 1

    original = agent_module.discover_mcp_tools
    _install_discovery(lambda config: build_mcp_tools(FakeAdapter(config), [{"name": "first"}]))
    try:
        asyncio.run(run_case())
    finally:
        agent_module.discover_mcp_tools = original
        config_file.unlink(missing_ok=True)


def test_the_background_timer_rediscovers_without_a_request() -> None:
    """The interval is an hour in production; one second here proves the task is wired."""
    config_file = Path(os.environ.get("TEMP", "/tmp")) / "mcp-timer-smoke.json"

    async def run_case() -> None:
        config_file.write_text(
            json.dumps({"servers": [{"name": "ha", "url": "http://ha/mcp", "prefix": "ha_"}]}),
            encoding="utf-8",
        )
        runtime = AgentRuntime(
            settings=Settings(enable_mcp=True, mcp_servers_file=str(config_file), mcp_refresh_interval_seconds=1)
        )
        await runtime.initialize()

        assert runtime.mcp_refresh_task is not None
        assert "ha_first" in runtime.tool_registry.tool_names()

        _install_discovery(lambda config: build_mcp_tools(FakeAdapter(config), [{"name": "second"}]))
        await asyncio.sleep(1.4)

        assert "ha_second" in runtime.tool_registry.tool_names()

        await runtime.shutdown()

        assert runtime.mcp_refresh_task is None

    original = agent_module.discover_mcp_tools
    _install_discovery(lambda config: build_mcp_tools(FakeAdapter(config), [{"name": "first"}]))
    try:
        asyncio.run(run_case())
    finally:
        agent_module.discover_mcp_tools = original
        config_file.unlink(missing_ok=True)


def test_a_broken_config_file_is_reported_not_fatal() -> None:
    async def run_case() -> None:
        runtime = AgentRuntime(
            settings=Settings(enable_mcp=True, mcp_servers_file=str(ROOT / "config" / "does-not-exist.json"))
        )
        await runtime.initialize()

        snapshot = runtime.health_snapshot()

        assert runtime.agent_service is not None
        assert snapshot["mcpServers"] == []
        assert "does-not-exist.json" in str(snapshot["mcpConfigError"])
        assert "echo" in snapshot["tools"]

    asyncio.run(run_case())


def _install_discovery(build: "callable") -> None:
    async def discovery(config: MCPServerConfig) -> list[MCPTool]:
        return build(config)

    agent_module.discover_mcp_tools = discovery
