from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from faster_whisper import WhisperModel


TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MODEL_SIZE = os.getenv("TRANSCRIBE_MODEL_SIZE", "base")
MODEL_DEVICE = os.getenv("TRANSCRIBE_DEVICE", "cpu")
MODEL_COMPUTE_TYPE = os.getenv("TRANSCRIBE_COMPUTE_TYPE", "int8")


app = FastAPI(title="telegram-transcribe", version="0.1.0")
model = WhisperModel(MODEL_SIZE, device=MODEL_DEVICE, compute_type=MODEL_COMPUTE_TYPE)


class TranscribeRequest(BaseModel):
    file_id: str = Field(..., description="Telegram voice file_id")
    language: str | None = Field(default=None, description="Optional language hint, e.g. en, de")


class TranscribeResponse(BaseModel):
    text: str
    detected_language: str | None = None
    file_path: str | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest) -> TranscribeResponse:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not configured")

    file_path = await _resolve_telegram_file_path(request.file_id)
    tmp_file = await _download_telegram_file(file_path)

    try:
        text, detected_language = await _transcribe_audio_file(tmp_file, language=request.language)
        return TranscribeResponse(
            text=text,
            detected_language=detected_language,
            file_path=file_path,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        tmp_file.unlink(missing_ok=True)


@app.post("/transcribe/audio", response_model=TranscribeResponse)
async def transcribe_audio(file: UploadFile = File(...), language: str | None = None) -> TranscribeResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was uploaded")

    tmp_file = None
    try:
        suffix = Path(file.filename).suffix or ".wav"
        with tempfile.NamedTemporaryFile(prefix="desktop_audio_", suffix=suffix, delete=False) as tmp:
            tmp.write(await file.read())
            tmp_file = Path(tmp.name)
        text, detected_language = await _transcribe_audio_file(tmp_file, language=language)
        return TranscribeResponse(text=text, detected_language=detected_language, file_path=str(tmp_file))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        if tmp_file is not None:
            tmp_file.unlink(missing_ok=True)


async def _transcribe_audio_file(file_path: Path, language: str | None = None) -> tuple[str, str | None]:
    segments, info = model.transcribe(str(file_path), language=language)
    text = "".join(segment.text for segment in segments).strip()
    return text, getattr(info, "language", None)


async def _resolve_telegram_file_path(file_id: str) -> str:
    url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/getFile"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params={"file_id": file_id})
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

    if not payload.get("ok"):
        raise HTTPException(status_code=400, detail=f"Telegram getFile failed: {payload}")

    result = payload.get("result") or {}
    file_path = result.get("file_path")
    if not file_path:
        raise HTTPException(status_code=400, detail="Telegram did not return file_path")
    return file_path


async def _download_telegram_file(file_path: str) -> Path:
    url = f"{TELEGRAM_API_BASE}/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    suffix = Path(file_path).suffix or ".oga"

    with tempfile.NamedTemporaryFile(prefix="voice_", suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        tmp_path.write_bytes(response.content)

    return tmp_path
