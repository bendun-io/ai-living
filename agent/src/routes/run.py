from fastapi import APIRouter

from src.agent.agent import AgentRuntime
from src.models import AgentRunRequest


def build_run_router(runtime: AgentRuntime) -> APIRouter:
    router = APIRouter()

    @router.post("/agent/run")
    async def run_agent(request: AgentRunRequest):
        return await runtime.run(request)

    return router
