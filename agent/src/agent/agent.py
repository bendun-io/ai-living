from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging

from src.callbacks.callback import CallbackClient
from src.config import Settings
from src.llm.openai_client import LocalLLMClient, OpenAIResponsesClient
from src.memory.memory import MemoryStore
from src.skills.library import SkillLibrary
from src.tools.adapters.local import build_local_tools
from src.tools.adapters.mcp import MCPServerConfig, discover_mcp_tools, load_mcp_server_configs
from src.tools.adapters.rest import fetch_rest_tool_definitions
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

from .executor import AgentService


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MCPServerStatus:
    """What the last discovery attempt against one MCP server produced."""

    name: str
    url: str
    prefix: str
    tools: int = 0
    error: str | None = None
    last_success_at: str | None = None
    last_attempt_at: str | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "prefix": self.prefix,
            "tools": self.tools,
            "error": self.error,
            "lastSuccessAt": self.last_success_at,
            "lastAttemptAt": self.last_attempt_at,
        }


@dataclass(slots=True)
class AgentRuntime:
    settings: Settings
    tool_registry: ToolRegistry | None = None
    agent_service: AgentService | None = None
    skill_library: SkillLibrary | None = None
    utils_lists_discovery_error: str | None = None
    utils_lists_tools_loaded: int = 0
    mcp_config_error: str | None = None
    mcp_server_configs: list[MCPServerConfig] = field(default_factory=list)
    mcp_status: dict[str, MCPServerStatus] = field(default_factory=dict)
    mcp_tool_names: dict[str, list[str]] = field(default_factory=dict)
    mcp_refresh_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        self.utils_lists_discovery_error = None
        self.utils_lists_tools_loaded = 0
        self.skill_library = SkillLibrary.default()
        registry = ToolRegistry()
        self.tool_registry = registry
        for tool in build_local_tools(self.skill_library):
            registry.register(tool)

        if self.settings.enable_mcp:
            self._load_mcp_server_configs()
            await self.refresh_mcp_tools()
            self._start_mcp_refresh_task()

        if self.settings.enable_utils_lists_tools:
            try:
                rest_tools = await fetch_rest_tool_definitions(self.settings.utils_lists_base_url)
                for tool in rest_tools:
                    registry.register(tool)
                self.utils_lists_tools_loaded = len(rest_tools)
                logger.info(
                    "Loaded %s utils-lists tools from %s",
                    self.utils_lists_tools_loaded,
                    self.settings.utils_lists_base_url,
                )
            except Exception as exc:  # noqa: BLE001
                self.utils_lists_discovery_error = str(exc)
                logger.warning(
                    "Failed to discover utils-lists tools from %s: %s",
                    self.settings.utils_lists_base_url,
                    exc,
                )

        if self.settings.openai_api_key:
            llm_client = OpenAIResponsesClient(api_key=self.settings.openai_api_key, model=self.settings.openai_model)
        else:
            llm_client = LocalLLMClient()

        self.agent_service = AgentService(
            llm_client=llm_client,
            tool_registry=registry,
            tool_executor=ToolExecutor(registry),
            memory_store=MemoryStore(),
            callback_client=CallbackClient(self.settings.callback_url),
            skill_library=self.skill_library,
        )

    async def shutdown(self) -> None:
        task = self.mcp_refresh_task
        self.mcp_refresh_task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _load_mcp_server_configs(self) -> None:
        self.mcp_config_error = None
        try:
            self.mcp_server_configs = load_mcp_server_configs(self.settings.mcp_servers_file)
        except Exception as exc:  # noqa: BLE001
            self.mcp_server_configs = []
            self.mcp_config_error = str(exc)
            logger.warning("Failed to load MCP server config %s: %s", self.settings.mcp_servers_file, exc)
            return

        self.mcp_status = {
            config.name: MCPServerStatus(name=config.name, url=config.url, prefix=config.prefix)
            for config in self.mcp_server_configs
        }

    async def refresh_mcp_tools(self) -> None:
        """Rediscover every configured MCP server and swap its tools in the registry.

        Each server is handled independently: a server that is down keeps the tools it
        published last time rather than losing them, because a transient network blip
        should not silently shrink what the planner can do.
        """
        registry = self.tool_registry
        if registry is None:
            return

        for config in self.mcp_server_configs:
            status = self.mcp_status.setdefault(
                config.name,
                MCPServerStatus(name=config.name, url=config.url, prefix=config.prefix),
            )
            status.last_attempt_at = _utc_now()
            try:
                tools = await discover_mcp_tools(config)
            except Exception as exc:  # noqa: BLE001
                status.error = str(exc)
                logger.warning("MCP discovery failed for %s (%s): %s", config.name, config.url, exc)
                continue

            for stale_name in self.mcp_tool_names.get(config.name, []):
                registry.unregister(stale_name)
            for tool in tools:
                registry.register(tool)

            self.mcp_tool_names[config.name] = [tool.name for tool in tools]
            status.tools = len(tools)
            status.error = None
            status.last_success_at = status.last_attempt_at
            logger.info("Loaded %s MCP tool(s) from %s (%s)", len(tools), config.name, config.url)

    def _start_mcp_refresh_task(self) -> None:
        interval = self.settings.mcp_refresh_interval_seconds
        if interval <= 0 or not self.mcp_server_configs:
            return
        if self.mcp_refresh_task is not None and not self.mcp_refresh_task.done():
            return
        self.mcp_refresh_task = asyncio.create_task(self._mcp_refresh_loop(interval))
        logger.info("MCP tool discovery will refresh every %ss", interval)

    async def _mcp_refresh_loop(self, interval: int) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.refresh_mcp_tools()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Periodic MCP tool refresh failed")

    async def run(self, request):
        if self.agent_service is None:
            await self.initialize()
        return await self.agent_service.run(request)

    def health_snapshot(self) -> dict[str, object]:
        return {
            "mcpEnabled": self.settings.enable_mcp,
            "mcpServersFile": self.settings.mcp_servers_file,
            "mcpRefreshIntervalSeconds": self.settings.mcp_refresh_interval_seconds,
            "mcpConfigError": self.mcp_config_error,
            "mcpServers": [status.snapshot() for status in self.mcp_status.values()],
            "utilsListsToolsEnabled": self.settings.enable_utils_lists_tools,
            "utilsListsBaseUrl": self.settings.utils_lists_base_url,
            "utilsListsDiscoveredTools": self.utils_lists_tools_loaded,
            "utilsListsDiscoveryError": self.utils_lists_discovery_error,
            "tools": self.tool_registry.tool_names() if self.tool_registry else [],
            "toolNameCollisions": self.tool_registry.collisions() if self.tool_registry else [],
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
