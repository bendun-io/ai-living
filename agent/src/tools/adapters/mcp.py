from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


DEFAULT_MCP_SERVERS_FILE = "config/mcp-servers.json"
SUPPORTED_TRANSPORTS = {"streamable_http", "sse"}

_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PREFIX_SEPARATORS = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class MCPServerConfig:
    """One entry from the MCP servers file."""

    name: str
    url: str
    prefix: str = ""
    transport: str = "streamable_http"
    token: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0

    def request_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        return headers


def default_prefix(server_name: str) -> str:
    """Derive a tool-name prefix from a server name.

    Every discovered tool is namespaced by default because MCP servers pick their own
    tool names with no knowledge of each other - Home Assistant's `GetLiveContext` and a
    second server's `GetLiveContext` would otherwise silently replace one another in the
    registry. An explicit empty `prefix` in the config opts out.
    """
    slug = _PREFIX_SEPARATORS.sub("_", server_name.strip().lower()).strip("_")
    return f"{slug}_" if slug else ""


def _expand_env(value: str) -> str:
    """Substitute ${VAR} placeholders so the config file can stay free of secrets."""

    def replace(match: re.Match[str]) -> str:
        variable = match.group(1)
        resolved = os.getenv(variable)
        if resolved is None:
            logger.warning("MCP config references ${%s}, which is not set; using an empty string", variable)
            return ""
        return resolved

    return _ENV_PLACEHOLDER.sub(replace, value)


def _resolve_config_path(path: str | None) -> Path:
    """Resolve the config path against the working directory, then the project root.

    The container runs uvicorn from /app, but tests and local runs start from wherever
    the developer happens to be, so a relative default has to be anchored to something
    stable as well.
    """
    candidate = Path(path or DEFAULT_MCP_SERVERS_FILE).expanduser()
    if candidate.is_absolute():
        return candidate

    cwd_candidate = Path.cwd() / candidate
    if cwd_candidate.exists():
        return cwd_candidate

    project_root = Path(__file__).resolve().parents[3]
    return project_root / candidate


def parse_mcp_server_configs(payload: Any) -> list[MCPServerConfig]:
    """Turn parsed JSON into server configs, skipping unusable entries rather than failing."""
    if isinstance(payload, dict):
        raw_servers = payload.get("servers", [])
    elif isinstance(payload, list):
        raw_servers = payload
    else:
        raise ValueError("MCP servers file must contain an object with a 'servers' array, or an array")

    if not isinstance(raw_servers, list):
        raise ValueError("'servers' must be an array")

    configs: list[MCPServerConfig] = []
    seen: set[str] = set()

    for entry in raw_servers:
        if not isinstance(entry, dict):
            logger.warning("Ignoring non-object entry in MCP servers file: %r", entry)
            continue

        name = str(entry.get("name", "")).strip()
        url = _expand_env(str(entry.get("url", "")).strip())
        if not name or not url:
            logger.warning("Ignoring MCP server entry without a name and url: %r", entry)
            continue

        if entry.get("enabled", True) is False:
            logger.info("MCP server %r is disabled in the config file; skipping", name)
            continue

        if name in seen:
            logger.warning("Duplicate MCP server name %r; the later entry wins", name)
        seen.add(name)

        raw_prefix = entry.get("prefix")
        prefix = default_prefix(name) if raw_prefix is None else str(raw_prefix)

        transport = str(entry.get("transport", "streamable_http")).strip().lower()
        if transport not in SUPPORTED_TRANSPORTS:
            logger.warning(
                "MCP server %r requests unsupported transport %r; falling back to streamable_http",
                name,
                transport,
            )
            transport = "streamable_http"

        token = _resolve_token(name, entry)

        raw_headers = entry.get("headers", {})
        headers: dict[str, str] = {}
        if isinstance(raw_headers, dict):
            headers = {str(key): _expand_env(str(value)) for key, value in raw_headers.items()}
        elif raw_headers:
            logger.warning("Ignoring non-object 'headers' for MCP server %r", name)

        try:
            timeout_seconds = float(entry.get("timeoutSeconds", 30))
        except (TypeError, ValueError):
            logger.warning("Invalid 'timeoutSeconds' for MCP server %r; using 30", name)
            timeout_seconds = 30.0

        configs.append(
            MCPServerConfig(
                name=name,
                url=url,
                prefix=prefix,
                transport=transport,
                token=token,
                headers=headers,
                timeout_seconds=timeout_seconds,
            )
        )

    return configs


def _resolve_token(name: str, entry: dict[str, Any]) -> str | None:
    """Prefer `tokenEnv` over a literal `token` so the config file can be committed."""
    token_env = entry.get("tokenEnv")
    if token_env:
        token = os.getenv(str(token_env))
        if not token:
            logger.warning(
                "MCP server %r reads its token from %s, which is not set; connecting unauthenticated",
                name,
                token_env,
            )
        return token or None

    raw_token = entry.get("token")
    if not raw_token:
        return None
    return _expand_env(str(raw_token)) or None


def load_mcp_server_configs(path: str | None = None) -> list[MCPServerConfig]:
    """Read the MCP servers file. Raises if it is missing or malformed."""
    config_path = _resolve_config_path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    configs = parse_mcp_server_configs(payload)
    logger.info("Loaded %s MCP server(s) from %s", len(configs), config_path)
    return configs


@dataclass(slots=True)
class MCPTool:
    """A remote MCP tool, exposed to the planner under its prefixed name."""

    name: str
    description: str
    input_schema: dict[str, Any]
    remote_name: str
    adapter: "MCPToolAdapter"

    async def execute(self, arguments: dict[str, Any]) -> Any:
        return await self.adapter.call_tool(self.remote_name, arguments)


@dataclass(slots=True)
class MCPToolAdapter:
    """Talks to one MCP server over HTTP.

    A session is opened per call rather than held open for the process lifetime: the
    Streamable HTTP transport is stateless, and a short-lived session means a server
    restart or a dropped connection costs one failed tool call instead of leaving the
    adapter permanently wedged.
    """

    config: MCPServerConfig

    @property
    def server_url(self) -> str:
        return self.config.url

    @asynccontextmanager
    async def _session(self):
        # Imported lazily so the module stays importable when the SDK is absent, which
        # keeps ENABLE_MCP=false deployments and the offline smoke tests working.
        from mcp import ClientSession

        headers = self.config.request_headers()
        if self.config.transport == "sse":
            from mcp.client.sse import sse_client

            transport = sse_client(self.config.url, headers=headers, timeout=self.config.timeout_seconds)
        else:
            from mcp.client.streamable_http import streamablehttp_client

            transport = streamablehttp_client(
                self.config.url,
                headers=headers,
                timeout=timedelta(seconds=self.config.timeout_seconds),
            )

        async with transport as streams:
            read_stream, write_stream = streams[0], streams[1]
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    async def list_tools(self) -> list[dict[str, Any]]:
        raw_tools: list[dict[str, Any]] = []
        async with self._session() as session:
            cursor: str | None = None
            while True:
                listed = await session.list_tools(cursor=cursor)
                raw_tools.extend(
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        # MCP speaks camelCase; the registry protocol speaks snake_case.
                        "input_schema": tool.inputSchema or {},
                    }
                    for tool in listed.tools
                )
                cursor = getattr(listed, "nextCursor", None)
                if not cursor:
                    return raw_tools

    async def call_tool(self, remote_name: str, arguments: dict[str, Any]) -> Any:
        async with self._session() as session:
            result = await session.call_tool(remote_name, arguments)
        return self._unwrap(remote_name, result)

    def _unwrap(self, remote_name: str, result: Any) -> Any:
        """Flatten an MCP tool result into something the planner can read.

        A tool-level error is re-raised so ToolExecutor records it as a failed ToolResult
        carrying the server's message, the same shape a local tool raising would produce.
        """
        blocks = getattr(result, "content", None) or []
        texts = [getattr(block, "text", "") for block in blocks if getattr(block, "type", None) == "text"]
        joined = "\n".join(text for text in texts if text)

        if getattr(result, "isError", False):
            raise RuntimeError(joined or f"MCP tool '{remote_name}' reported an error")

        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        if joined:
            return joined
        if blocks:
            return [block.model_dump(mode="json") for block in blocks]
        return None


def build_mcp_tools(adapter: MCPToolAdapter, raw_tools: list[dict[str, Any]]) -> list[MCPTool]:
    """Map a server's tool listing onto registry tools, applying the server prefix."""
    tools: list[MCPTool] = []
    for item in raw_tools:
        remote_name = str(item.get("name", "")).strip()
        if not remote_name:
            logger.warning("MCP server %r advertised a tool without a name; skipping", adapter.config.name)
            continue

        input_schema = item.get("input_schema", {})
        if not isinstance(input_schema, dict):
            input_schema = {}

        tools.append(
            MCPTool(
                name=f"{adapter.config.prefix}{remote_name}",
                description=str(item.get("description", "")),
                input_schema=input_schema,
                # The prefix is local namespacing; the server only knows its own name.
                remote_name=remote_name,
                adapter=adapter,
            )
        )

    return tools


async def discover_mcp_tools(config: MCPServerConfig) -> list[MCPTool]:
    adapter = MCPToolAdapter(config=config)
    return build_mcp_tools(adapter, await adapter.list_tools())
