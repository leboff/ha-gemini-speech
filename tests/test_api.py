"""Test HTTP, pagination, cache throttling, and error boundaries offline."""

import asyncio
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.gemini_speech.api import (
    ApiError,
    AuthError,
    ConnectionError,
    GeminiSpeechClient,
)
from custom_components.gemini_speech.audio import extract_audio
from custom_components.gemini_speech.const import API_URL


@pytest.fixture
async def client(hass, aioclient_mock):
    return GeminiSpeechClient(async_get_clientsession(hass), "test-key")


async def test_pagination_and_cache(client, aioclient_mock, load_capture):
    catalog = load_capture("voices_en_us")
    aioclient_mock.get(
        f"{API_URL}/voices?page_token={catalog['next_page_token']}", json={"voices": []}
    )
    aioclient_mock.get(f"{API_URL}/voices", json=catalog)
    await asyncio.gather(client.refresh_voices(), client.refresh_voices())
    assert client.voices == catalog["voices"]
    assert aioclient_mock.call_count == 2
    assert "kore" in client.supported_voices("en-US")
    assert len(client.supported_voices("zz-ZZ")) == 30
    assert "custom" in client.supported_voices("en-US", "custom")
    first_refresh = client.last_refresh
    await client.refresh_voices()
    assert aioclient_mock.call_count == 2
    with patch(
        "custom_components.gemini_speech.api.time.monotonic",
        return_value=client._last_attempt + 86401,
    ):
        await client.refresh_voices()
    assert aioclient_mock.call_count == 4
    assert client.last_refresh >= first_refresh


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_validation_auth(client, aioclient_mock, load_capture, status):
    aioclient_mock.get(
        f"{API_URL}/voices", status=status, json=load_capture("err_bad_key")["response"]
    )
    with pytest.raises(AuthError, match="API key not valid"):
        await client.validate_key()
    assert aioclient_mock.mock_calls[0][1].query["page_size"] == "1"


async def test_failed_cache_uses_static_and_throttles(client, aioclient_mock):
    aioclient_mock.get(f"{API_URL}/voices", exc=aiohttp.ClientConnectionError())
    await client.refresh_voices()
    await client.refresh_voices()
    assert aioclient_mock.call_count == 1
    assert len(client.supported_voices("en-US")) == 30


@pytest.mark.parametrize("name", ["ok_plain", "ok_lite", "ok_style_tags"])
async def test_exact_synthesis(client, aioclient_mock, load_capture, name):
    capture = load_capture(name)
    aioclient_mock.get(f"{API_URL}/voices", json={"voices": []})
    aioclient_mock.post(f"{API_URL}/interactions", json=capture["response"])
    request = capture["request"]
    content = request["input"][0]["content"][0]
    style = content.get("annotations", [{}])[0].get("style")
    assert (
        await client.synthesize(content["text"], "Kore", style, request["model"])
        == extract_audio(capture["response"])[1]
    )
    post = aioclient_mock.mock_calls[-1]
    assert post[2] == request
    assert post[3]["x-goog-api-key"] == "test-key"


@pytest.mark.parametrize("name", ["err_bad_key", "err_bad_voice", "err_bad_model"])
async def test_api_errors(client, aioclient_mock, load_capture, name):
    capture = load_capture(name)
    aioclient_mock.get(f"{API_URL}/voices", json={"voices": []})
    aioclient_mock.post(
        f"{API_URL}/interactions", status=capture["status"], json=capture["response"]
    )
    with pytest.raises(ApiError, match=f"Gemini TTS error {capture['status']}:"):
        await client.synthesize("hello", "kore", "", "model")


async def test_timeout(client, aioclient_mock):
    aioclient_mock.get(f"{API_URL}/voices", exc=TimeoutError())
    with pytest.raises(ConnectionError, match="Gemini TTS timed out"):
        await client.validate_key()


async def test_redact_error(client, aioclient_mock):
    aioclient_mock.get(
        f"{API_URL}/voices", status=400, json={"error": {"message": "invalid test-key"}}
    )
    with pytest.raises(AuthError) as error:
        await client.validate_key()
    assert "test-key" not in str(error.value)


async def test_failed_refresh_retains_previous_catalog(
    client, aioclient_mock, load_capture
):
    catalog = load_capture("voices_en_us")
    catalog.pop("next_page_token")
    aioclient_mock.get(f"{API_URL}/voices", json=catalog)
    await client.refresh_voices()
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/voices", status=503, text="Unavailable")
    with patch(
        "custom_components.gemini_speech.api.time.monotonic",
        return_value=client._last_attempt + 86401,
    ):
        await client.refresh_voices()
    assert client.voices == catalog["voices"]
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize(
    "body,expected",
    [
        ("not json", "invalid JSON"),
        ('{"steps": []}', "Gemini returned no audio"),
        (
            '{"steps": [{"type": "model_output", "content": [{"type": "audio", "mime_type": "audio/wav", "data": "@@invalid@@"}]}]}',
            "Only base64 data",
        ),
    ],
)
async def test_malformed_audio_errors(client, aioclient_mock, body, expected):
    aioclient_mock.get(f"{API_URL}/voices", json={"voices": []})
    aioclient_mock.post(f"{API_URL}/interactions", text=body)
    with pytest.raises(ApiError, match=expected):
        await client.synthesize("hello", "kore", "", "model")


async def test_request_timeout_is_120_seconds(client, aioclient_mock):
    aioclient_mock.get(f"{API_URL}/voices", json={"voices": []})
    with patch.object(
        client._session, "request", wraps=client._session.request
    ) as request:
        await client.validate_key()
    assert request.call_args.kwargs["timeout"].total == 120
