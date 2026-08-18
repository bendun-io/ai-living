from fastapi import FastAPI

from src.agent.agent import AgentRuntime
from src.config import Settings
from src.observability.trace import configure_logging
from src.routes.run import build_run_router


settings = Settings.from_env()
configure_logging(settings.log_level)

runtime = AgentRuntime(settings=settings)
app = FastAPI(title="ai-living-agent", version="0.1.0")


@app.on_event("startup")
async def on_startup() -> None:
    await runtime.initialize()


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "mcpEnabled": settings.enable_mcp,
        "tools": runtime.tool_registry.tool_names() if runtime.tool_registry else [],
    }


app.include_router(build_run_router(runtime))
