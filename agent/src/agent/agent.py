from __future__ import annotations

from dataclasses import dataclass

from src.callbacks.callback import CallbackClient
from src.config import Settings
from src.llm.openai_client import LocalLLMClient, OpenAIResponsesClient
from src.memory.memory import MemoryStore
from src.tools.adapters.local import build_local_tools
from src.tools.adapters.mcp import MCPToolAdapter
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

from .executor import AgentService


@dataclass(slots=True)
class AgentRuntime:
    settings: Settings
    tool_registry: ToolRegistry | None = None
    agent_service: AgentService | None = None

    async def initialize(self) -> None:
        registry = ToolRegistry()
        for tool in build_local_tools():
            registry.register(tool)

        if self.settings.enable_mcp:
            for server_url in self.settings.mcp_servers:
                adapter = MCPToolAdapter(server_url=server_url)
                for tool_data in await adapter.discover_tools():
                    registry.register(_DynamicTool(tool_data, adapter))

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
        )

    async def run(self, request):
        if self.agent_service is None:
            await self.initialize()
        return await self.agent_service.run(request)


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
