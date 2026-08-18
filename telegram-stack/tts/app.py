from __future__ import annotations

import io
import os
import subprocess
import tempfile
import wave
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from kokoro_onnx import Kokoro
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("kokoro-onnx must be installed") from exc


DEFAULT_ALLOWED_VOICES = [
    "af_alloy",
    "af_aoede",
    "af_bella",
    "af_heart",
    "af_jessica",
    "af_kore",
    "af_nicole",
    "af_nova",
    "af_river",
    "am_adam",
    "am_echo",
    "am_eric",
    "bf_emma",
    "bf_isabella",
    "bm_george",
    "bm_lewis",
]

KOKORO_MODEL_PATH = os.getenv("KOKORO_MODEL_PATH", "").strip()
KOKORO_VOICES_PATH = os.getenv("KOKORO_VOICES_PATH", "").strip()
KOKORO_LANGUAGE = os.getenv("KOKORO_LANGUAGE", "en-us").strip()
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))
TTS_MAX_TEXT_LENGTH = int(os.getenv("TTS_MAX_TEXT_LENGTH", "1500"))
TTS_ALLOWED_VOICES = [
    voice.strip() for voice in os.getenv("TTS_ALLOWED_VOICES", ",".join(DEFAULT_ALLOWED_VOICES)).split(",") if voice.strip()
]

app = FastAPI(title="telegram-tts", version="0.1.0")
engine: Kokoro | None = None
startup_error: str | None = None


class OutputFormat(str, Enum):
    wav = "wav"
    mp3 = "mp3"
    ogg = "ogg"


class TtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice: str = Field(..., description="Kokoro voice id")
    text: str = Field(..., min_length=1, max_length=TTS_MAX_TEXT_LENGTH)
    format: OutputFormat = Field(..., description="Output audio format")

    @field_validator("voice")
    @classmethod
    def validate_voice(cls, value: str) -> str:
        voice = value.strip()
        if not voice:
            raise ValueError("voice must not be empty")
        return voice

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("text must not be empty")
        return text


@app.on_event("startup")
async def startup() -> None:
    global engine, startup_error
    try:
        engine = _create_engine()
        startup_error = None
    except Exception as exc:  # noqa: BLE001
        # Keep the API process alive and expose a clear configuration error.
        engine = None
        startup_error = str(exc)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "engineLoaded": engine is not None,
        "startupError": startup_error,
        "requiredEnv": {
            "KOKORO_MODEL_PATH": KOKORO_MODEL_PATH,
            "KOKORO_VOICES_PATH": KOKORO_VOICES_PATH,
        },
        "allowedVoices": TTS_ALLOWED_VOICES,
    }


@app.post("/tts")
async def tts(payload: TtsRequest) -> Response:
    if payload.voice not in TTS_ALLOWED_VOICES:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Unknown voice '{payload.voice}'",
                "allowedVoices": TTS_ALLOWED_VOICES,
            },
        )

    if engine is None:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Kokoro engine is not initialized",
                "startupError": startup_error,
                "hint": "Set KOKORO_MODEL_PATH and KOKORO_VOICES_PATH to valid files.",
            },
        )

    try:
        samples, sample_rate = _synthesize(engine, text=payload.text, voice=payload.voice)
        wav_bytes = _to_wav_bytes(samples, sample_rate)
        audio_bytes = _convert_audio(wav_bytes, payload.format)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {exc}") from exc

    media_type = {
        OutputFormat.wav: "audio/wav",
        OutputFormat.mp3: "audio/mpeg",
        OutputFormat.ogg: "audio/ogg",
    }[payload.format]

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    filename = f"tts_{payload.voice}_{timestamp}.{payload.format.value}"

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _create_engine() -> Kokoro:
    if not KOKORO_MODEL_PATH or not KOKORO_VOICES_PATH:
        raise ValueError("KOKORO_MODEL_PATH and KOKORO_VOICES_PATH must both be set")

    model_path = Path(KOKORO_MODEL_PATH)
    voices_path = Path(KOKORO_VOICES_PATH)

    if not model_path.exists():
        raise FileNotFoundError(f"Kokoro model file not found: {model_path}")
    if not voices_path.exists():
        raise FileNotFoundError(f"Kokoro voices file not found: {voices_path}")

    kwargs: dict[str, str] = {}
    kwargs["model_path"] = str(model_path)
    kwargs["voices_path"] = str(voices_path)

    try:
        return Kokoro(**kwargs)
    except TypeError:
        # Compatibility for older signatures.
        return Kokoro(str(model_path), str(voices_path))


def _synthesize(tts_engine: Kokoro, text: str, voice: str) -> tuple[np.ndarray, int]:
    try:
        result = tts_engine.create(text=text, voice=voice, speed=KOKORO_SPEED, lang=KOKORO_LANGUAGE)
    except TypeError:
        result = tts_engine.create(text, voice, KOKORO_SPEED, KOKORO_LANGUAGE)

    if not isinstance(result, tuple) or len(result) < 2:
        raise RuntimeError("Unexpected Kokoro output format")

    samples = np.asarray(result[0], dtype=np.float32)
    sample_rate = int(result[1])

    if samples.size == 0:
        raise RuntimeError("Kokoro returned empty audio samples")
    if sample_rate <= 0:
        raise RuntimeError("Kokoro returned invalid sample rate")

    return samples, sample_rate


def _to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    clamped = np.clip(samples, -1.0, 1.0)
    pcm = (clamped * 32767.0).astype(np.int16)

    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return buffer.getvalue()


def _convert_audio(wav_bytes: bytes, output_format: OutputFormat) -> bytes:
    if output_format == OutputFormat.wav:
        return wav_bytes

    suffix = f".{output_format.value}"
    with tempfile.NamedTemporaryFile(prefix="tts_in_", suffix=".wav", delete=False) as in_tmp:
        in_path = Path(in_tmp.name)
        in_path.write_bytes(wav_bytes)

    with tempfile.NamedTemporaryFile(prefix="tts_out_", suffix=suffix, delete=False) as out_tmp:
        out_path = Path(out_tmp.name)

    try:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            str(out_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Audio conversion failed: {result.stderr.strip()}")
        return out_path.read_bytes()
    finally:
        in_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)
