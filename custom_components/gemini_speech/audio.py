"""Pure response parsing and lossless PCM-to-WAV wrapping."""

import base64
import io
import json
import re
import wave
from typing import Any


def extract_audio(response: dict[str, Any]) -> tuple[str, bytes]:
    """Extract the last audio block from model output, ignoring user input."""
    audio = None
    for step in response.get("steps", []):
        if step.get("type") != "model_output":
            continue
        for content in step.get("content", []):
            if content.get("type") == "audio":
                audio = content
    if audio is None:
        raise ValueError("Gemini returned no audio")
    return audio["mime_type"], base64.b64decode(audio["data"], validate=True)


def ensure_wav(mime: str, data: bytes) -> bytes:
    """Pass WAV through unchanged, or wrap raw mono 16-bit PCM without conversion."""
    media_type = mime.split(";", 1)[0].strip().lower()
    if media_type in ("audio/wav", "audio/x-wav", "audio/wave"):
        return data
    if media_type not in ("audio/l16", "audio/pcm"):
        raise ValueError(f"Unsupported audio MIME type: {mime}")
    rate_match = re.search(r"(?:^|;)\s*rate\s*=\s*(\d+)", mime, re.IGNORECASE)
    rate = int(rate_match[1]) if rate_match else 24000
    if rate <= 0:
        raise ValueError("Invalid PCM sample rate")
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(data)
        return output.getvalue()


def parse_error(status: int, body: Any) -> str:
    """Read Google's object/list errors, with a useful non-JSON fallback."""
    if isinstance(body, (str, bytes)):
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            return body.strip() or f"HTTP {status}"
        return parse_error(status, parsed)
    if isinstance(body, list):
        return "; ".join(parse_error(status, item) for item in body) or f"HTTP {status}"
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            return str(error.get("message") or error.get("status") or f"HTTP {status}")
        return str(error)
    return f"HTTP {status}"
