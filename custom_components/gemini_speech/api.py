"""Small aiohttp client for the Gemini Interactions API."""

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import aiohttp

from .audio import ensure_wav, extract_audio, parse_error
from .const import API_URL, REQUEST_TIMEOUT, STATIC_VOICES, VOICE_CACHE_SECONDS

_LOGGER = logging.getLogger(__name__)


class GeminiSpeechError(Exception):
    """Base error for Gemini Speech."""


class AuthError(GeminiSpeechError):
    """The API key was rejected."""


class ApiError(GeminiSpeechError):
    """The API rejected a request or returned invalid content."""


class ConnectionError(GeminiSpeechError):
    """The API could not be reached."""


class GeminiSpeechClient:
    """Own the shared HA session reference and an in-memory voice catalog."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key
        self.voices: list[dict[str, str]] = []
        self.last_refresh: datetime | None = None
        self._last_attempt: float | None = None
        self._refresh_lock = asyncio.Lock()

    def matches_key(self, api_key: str) -> bool:
        """Allow reloads to reuse the catalog unless the credentials changed."""
        return self._api_key == api_key

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with self._session.request(
                method,
                f"{API_URL}/{path}",
                headers={"x-goog-api-key": self._api_key},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                **kwargs,
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    message = parse_error(response.status, body).replace(
                        self._api_key, "**REDACTED**"
                    )
                    error = (
                        AuthError
                        if response.status in (400, 401, 403) and path == "voices"
                        else ApiError
                    )
                    raise error(f"Gemini TTS error {response.status}: {message}")
                try:
                    return await response.json(content_type=None)
                except (ValueError, TypeError) as err:
                    raise ApiError("Gemini returned invalid JSON") from err
        except TimeoutError as err:
            raise ConnectionError("Gemini TTS timed out") from err
        except aiohttp.ClientError as err:
            raise ConnectionError("Cannot connect to Gemini") from err

    async def validate_key(self) -> None:
        """Validate credentials with the smallest catalog request."""
        await self._request("GET", "voices", params={"page_size": 1})

    async def list_voices(self) -> list[dict[str, str]]:
        """Fetch every page of prebuilt voices, across languages."""
        voices = []
        params: dict[str, str | int] = {"type": "prebuilt", "page_size": 1000}
        seen_tokens: set[str] = set()
        while True:
            response = await self._request("GET", "voices", params=params)
            if not isinstance(response, dict) or not isinstance(
                response.get("voices"), list
            ):
                raise ApiError("Gemini returned an invalid voice catalog")
            voices.extend(
                voice
                for voice in response["voices"]
                if isinstance(voice, dict) and voice.get("id")
            )
            token = response.get("next_page_token")
            if not token:
                return voices
            if token in seen_tokens:
                raise ApiError("Gemini repeated a voice catalog page")
            seen_tokens.add(token)
            params["page_token"] = token

    async def refresh_voices(self) -> None:
        """Refresh at most daily, including failed attempts; coalesce concurrent calls."""
        async with self._refresh_lock:
            if (
                self._last_attempt is not None
                and time.monotonic() - self._last_attempt < VOICE_CACHE_SECONDS
            ):
                return
            self._last_attempt = time.monotonic()
            self.last_refresh = datetime.now(UTC)
            try:
                self.voices = await self.list_voices()
            except GeminiSpeechError:
                _LOGGER.warning(
                    "Could not refresh Gemini voices; using cached and static voices"
                )

    def supported_voices(
        self, language: str, current_voice: str | None = None
    ) -> dict[str, str]:
        """Merge multilingual defaults with matching catalog voices and a custom voice."""
        voices = dict(STATIC_VOICES)
        for voice in self.voices:
            if not voice.get("language_code", "").lower().startswith(language.lower()):
                continue
            name = voice.get("display_name", voice["id"])
            description = voice.get("description", "")[:40]
            voices[voice["id"]] = f"{name} ({description})" if description else name
        if current_voice:
            voices.setdefault(current_voice, current_voice)
        return voices

    async def synthesize(
        self, message: str, voice: str, style: str | None, model: str
    ) -> bytes:
        """Send text verbatim, with delivery direction in speech metadata."""
        # Catalog refresh happens at setup/reload only: a speech call must never wait on paging 2k+ voices.
        content: dict[str, Any] = {"type": "text", "text": message}
        if style:
            content["annotations"] = [{"type": "speech_metadata", "style": style}]
        payload = {
            "model": model,
            "input": [{"type": "user_input", "content": [content]}],
            "response_format": {"type": "audio"},
            "generation_config": {"speech_config": [{"voice": voice}]},
        }
        response = await self._request("POST", "interactions", json=payload)
        try:
            mime, audio = extract_audio(response)
            return ensure_wav(mime, audio)
        except (ValueError, KeyError, TypeError, AttributeError) as err:
            raise ApiError(str(err)) from err
