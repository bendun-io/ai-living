# Kokoro TTS Service

Minimal HTTP service for text-to-speech using Kokoro.

## Endpoint

- `POST /tts`
- `GET /health`

## Request Contract

`POST /tts` accepts exactly these JSON fields:

- `voice` (string)
- `text` (string)
- `format` (`wav` | `mp3` | `ogg`)

Unknown fields are rejected.

### Example Request

```json
{
  "voice": "af_bella",
  "text": "Hello from Kokoro TTS.",
  "format": "wav"
}
```

## Response

- Returns raw audio bytes directly.
- Content type by format:
  - `wav` -> `audio/wav`
  - `mp3` -> `audio/mpeg`
  - `ogg` -> `audio/ogg`
- Includes `Content-Disposition` attachment filename.

## URLs

- From host machine: `http://localhost:3020/tts`
- From containers on `telegram-stack` network: `http://tts:8000/tts`

## Required Configuration

`kokoro-onnx` requires both files to be present and configured:

- `KOKORO_MODEL_PATH` (path to `.onnx` model)
- `KOKORO_VOICES_PATH` (path to voices `.bin`)

If these are missing or invalid, the service now stays up but reports the problem via `GET /health` and returns `503` on `POST /tts`.

Example compose environment override:

```yaml
environment:
  KOKORO_MODEL_PATH: /models/kokoro-v1.0.onnx
  KOKORO_VOICES_PATH: /models/voices-v1.0.bin
volumes:
  - ./tts/models:/models:ro
```

## Quick curl Examples

Save WAV:

```bash
curl -X POST http://localhost:3020/tts \
  -H "Content-Type: application/json" \
  -d '{"voice":"af_bella","text":"Hello world","format":"wav"}' \
  --output out.wav
```

Save MP3:

```bash
curl -X POST http://localhost:3020/tts \
  -H "Content-Type: application/json" \
  -d '{"voice":"af_bella","text":"Hello world","format":"mp3"}' \
  --output out.mp3
```

Save OGG:

```bash
curl -X POST http://localhost:3020/tts \
  -H "Content-Type: application/json" \
  -d '{"voice":"af_bella","text":"Hello world","format":"ogg"}' \
  --output out.ogg
```

## Notes

- Invalid `voice` returns HTTP 400 with allowed voices.
- Empty text or unsupported format returns validation errors.
