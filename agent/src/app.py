from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.agent.agent import AgentRuntime
from src.config import Settings
from src.observability.trace import configure_logging
from src.routes.run import build_run_router


settings = Settings.from_env()
configure_logging(settings.log_level)

runtime = AgentRuntime(settings=settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await runtime.initialize()
    try:
        yield
    finally:
        await runtime.shutdown()


app = FastAPI(title="ai-living-agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", **runtime.health_snapshot()}


app.include_router(build_run_router(runtime))
