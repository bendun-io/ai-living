from __future__ import annotations

from dataclasses import dataclass, field
import os


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class Settings:
    agent_host: str = "0.0.0.0"
    agent_port: int = 8000
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    callback_url: str | None = None
    enable_mcp: bool = False
    mcp_servers: list[str] = field(default_factory=list)
    memory_provider: str = "memory"
    log_level: str = "info"
    enable_utils_lists_tools: bool = False
    utils_lists_base_url: str = "http://host.docker.internal:8010"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            agent_host=os.getenv("AGENT_HOST", "0.0.0.0"),
            agent_port=int(os.getenv("AGENT_PORT", "8000")),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            callback_url=os.getenv("CALLBACK_URL") or None,
            enable_mcp=_parse_bool(os.getenv("ENABLE_MCP"), False),
            mcp_servers=_parse_csv(os.getenv("MCP_SERVERS")),
            memory_provider=os.getenv("MEMORY_PROVIDER", "memory"),
            log_level=os.getenv("LOG_LEVEL", "info"),
            enable_utils_lists_tools=_parse_bool(os.getenv("ENABLE_UTILS_LISTS_TOOLS"), False),
            utils_lists_base_url=os.getenv("UTILS_LISTS_BASE_URL", "http://host.docker.internal:8010"),
        )
