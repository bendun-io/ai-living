from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app import app as existing_app


class AudioTranscribeRequest(BaseModel):
    language: str | None = None


@existing_app.post("/transcribe/audio", response_model=dict[str, Any])
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No uploaded file provided")

    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(prefix="desktop_audio_", suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        text = await _transcribe_from_path(tmp_path, language=language)
        return {"text": text, "detected_language": language or "en", "file_path": str(tmp_path)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


async def _transcribe_from_path(file_path: Path, language: str | None = None) -> str:
    from app import model

    segments, info = model.transcribe(str(file_path), language=language)
    return "".join(segment.text for segment in segments).strip()
