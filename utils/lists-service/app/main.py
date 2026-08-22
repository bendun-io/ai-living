from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core import _init_db
from app.routes_agent import router as agent_router
from app.routes_rest import router as rest_router

app = FastAPI(title="utils-lists", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    _init_db()


app.include_router(agent_router)
app.include_router(rest_router)

_static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_static_dir / "index.html")
