from __future__ import annotations

from dataclasses import dataclass
import logging

from src.callbacks.callback import CallbackClient
from src.config import Settings
from src.llm.openai_client import LocalLLMClient, OpenAIResponsesClient
from src.memory.memory import MemoryStore
from src.skills.library import SkillLibrary
from src.tools.adapters.local import build_local_tools
from src.tools.adapters.mcp import MCPToolAdapter
from src.tools.adapters.rest import fetch_rest_tool_definitions
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

from .executor import AgentService


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentRuntime:
    settings: Settings
    tool_registry: ToolRegistry | None = None
    agent_service: AgentService | None = None
    skill_library: SkillLibrary | None = None
    utils_lists_discovery_error: str | None = None
    utils_lists_tools_loaded: int = 0

    async def initialize(self) -> None:
        self.utils_lists_discovery_error = None
        self.utils_lists_tools_loaded = 0
        self.skill_library = SkillLibrary.default()
        registry = ToolRegistry()
        for tool in build_local_tools(self.skill_library):
            registry.register(tool)

        if self.settings.enable_mcp:
            for server_url in self.settings.mcp_servers:
                adapter = MCPToolAdapter(server_url=server_url)
                for tool_data in await adapter.discover_tools():
                    registry.register(_DynamicTool(tool_data, adapter))

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

        self.tool_registry = registry
        self.agent_service = AgentService(
            llm_client=llm_client,
            tool_registry=registry,
            tool_executor=ToolExecutor(registry),
            memory_store=MemoryStore(),
            callback_client=CallbackClient(self.settings.callback_url),
            skill_library=self.skill_library,
        )

    async def run(self, request):
        if self.agent_service is None:
            await self.initialize()
        return await self.agent_service.run(request)

    def health_snapshot(self) -> dict[str, object]:
        return {
            "mcpEnabled": self.settings.enable_mcp,
            "utilsListsToolsEnabled": self.settings.enable_utils_lists_tools,
            "utilsListsBaseUrl": self.settings.utils_lists_base_url,
            "utilsListsDiscoveredTools": self.utils_lists_tools_loaded,
            "utilsListsDiscoveryError": self.utils_lists_discovery_error,
            "tools": self.tool_registry.tool_names() if self.tool_registry else [],
        }


@dataclass(slots=True)
class _DynamicTool:
    tool_data: dict
    adapter: MCPToolAdapter

    @property
    def name(self) -> str:
        return self.tool_data["name"]

    @property
    def description(self) -> str:
        return self.tool_data.get("description", "")

    @property
    def input_schema(self) -> dict:
        return self.tool_data.get("input_schema", {})

    async def execute(self, arguments):
        return await self.adapter.execute(self.name, arguments)
