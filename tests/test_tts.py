"""Test the registered entities, HA TTS pipeline, and diagnostics with mock HTTP."""

from copy import deepcopy

import aiohttp
import pytest
from homeassistant.components import tts
from homeassistant.components.tts.const import DATA_COMPONENT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.gemini_speech.audio import extract_audio
from custom_components.gemini_speech.const import API_URL, DEFAULT_MODEL, DOMAIN
from custom_components.gemini_speech.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.fixture
async def entity(hass, configured_entry):
    return hass.data[DATA_COMPONENT].get_entity("tts.alice")


async def test_exact_request_and_audio(entity, gemini_http, load_capture):
    capture = load_capture("ok_style_tags")
    expected = deepcopy(capture["request"])
    expected["generation_config"]["speech_config"][0]["voice"] = "kore"
    message = expected["input"][0]["content"][0]["text"]
    extension, data = await entity.async_get_tts_audio(message, "en-US", {})
    assert extension == "wav"
    assert data == extract_audio(capture["response"])[1]
    assert gemini_http.mock_calls[-1][2] == expected
    assert gemini_http.mock_calls[-1][3]["x-goog-api-key"] == "test-key"
    assert entity.supported_options == ["voice", "style", "model"]
    assert entity.default_language == "en-US"
    assert {"en-GB", "en-AU"} <= set(entity.supported_languages)
    assert entity.has_entity_name and entity.name == ""
    assert entity.default_options == {
        "voice": "kore",
        "style": "warm, dry and conversational",
        "model": DEFAULT_MODEL,
    }
    assert not entity.async_supports_streaming_input()


@pytest.mark.parametrize("style", ["", None])
async def test_empty_style_override(entity, gemini_http, style):
    await entity.async_get_tts_audio("hello", "en-US", {"style": style})
    assert "annotations" not in gemini_http.mock_calls[-1][2]["input"][0]["content"][0]


async def test_voice_model_overrides_and_tags(entity, gemini_http):
    message = "Hello <short pause> café <chuckle> & <tsk>\nGoodbye."
    await entity.async_get_tts_audio(
        message,
        "en-US",
        {"voice": "puck", "model": "custom-model", "style": "cheerful"},
    )
    body = gemini_http.mock_calls[-1][2]
    assert body["model"] == "custom-model"
    assert body["generation_config"] == {"speech_config": [{"voice": "puck"}]}
    assert body["input"][0]["content"][0] == {
        "type": "text",
        "text": message,
        "annotations": [{"type": "speech_metadata", "style": "cheerful"}],
    }


async def test_ha_media_source_pipeline(hass, entity, gemini_http, load_capture):
    media_id = tts.generate_media_source_id(
        hass,
        message="Hello <short pause> friend",
        engine=entity.entity_id,
        options={"style": "", "preferred_format": "wav"},
        cache=False,
    )
    extension, data = await tts.async_get_media_source_audio(hass, media_id)
    assert extension == "wav"
    assert data.startswith(b"RIFF")
    assert gemini_http.mock_calls[-1][2]["input"][0]["content"][0] == {
        "type": "text",
        "text": "Hello <short pause> friend",
    }
    assert hass.states.get("tts.alice").state not in ("unknown", "unavailable")


@pytest.mark.parametrize("name", ["err_bad_key", "err_bad_voice", "err_bad_model"])
async def test_ha_errors(hass, entity, gemini_http, load_capture, name):
    capture = load_capture(name)
    gemini_http.clear_requests()
    gemini_http.post(
        f"{API_URL}/interactions", status=capture["status"], json=capture["response"]
    )
    body = capture["response"]
    message = (body[0] if isinstance(body, list) else body)["error"]["message"]
    with pytest.raises(HomeAssistantError) as error:
        await entity.async_get_tts_audio("hello", "en-US", {})
    assert str(error.value) == f"Gemini TTS error {capture['status']}: {message}"


@pytest.mark.parametrize(
    "exception,expected",
    [
        (TimeoutError(), "Gemini TTS timed out"),
        (aiohttp.ClientConnectionError(), "Cannot connect to Gemini"),
    ],
)
async def test_connection_errors(entity, gemini_http, exception, expected):
    gemini_http.clear_requests()
    gemini_http.post(f"{API_URL}/interactions", exc=exception)
    with pytest.raises(HomeAssistantError, match=expected):
        await entity.async_get_tts_audio("hello", "en-US", {})


async def test_no_audio_error(entity, gemini_http):
    gemini_http.clear_requests()
    gemini_http.post(f"{API_URL}/interactions", json={"steps": []})
    with pytest.raises(HomeAssistantError, match="^Gemini returned no audio$"):
        await entity.async_get_tts_audio("hello", "en-US", {})


async def test_long_message_unchanged(entity, gemini_http, caplog):
    message = "x" * 4001
    await entity.async_get_tts_audio(message, "en-US", {})
    assert gemini_http.mock_calls[-1][2]["input"][0]["content"][0]["text"] == message
    assert "may be truncated" in caplog.text
    assert message not in caplog.text


async def test_cached_catalog(entity, gemini_http, configured_entry, load_capture):
    assert (
        configured_entry.runtime_data.voices == load_capture("voices_en_us")["voices"]
    )
    initial_calls = gemini_http.call_count
    for _ in range(2):
        await entity.async_get_tts_audio("hello", "en-US", {})
    assert gemini_http.call_count == initial_calls + 2
    voices = entity.async_get_supported_voices("en-US")
    assert "kore" in {voice.voice_id for voice in voices}
    captured = load_capture("voices_en_us")["voices"][0]
    voice = next(v for v in voices if v.voice_id == captured["id"])
    assert voice.name == f"{captured['display_name']} ({captured['description'][:40]})"


async def test_failed_catalog_setup(hass, aioclient_mock, load_capture):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    aioclient_mock.get(f"{API_URL}/voices", exc=aiohttp.ClientConnectionError())
    aioclient_mock.post(
        f"{API_URL}/interactions", json=load_capture("ok_plain")["response"]
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": "test-key"},
        subentries_data=[
            {
                "subentry_type": "tts",
                "title": "Custom",
                "unique_id": None,
                "data": {"voice": "custom-voice"},
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entity = hass.data[DATA_COMPONENT].get_entity("tts.custom")
    voices = entity.async_get_supported_voices("en-US")
    assert len(voices) == 31
    assert {"kore", "custom-voice"} <= {voice.voice_id for voice in voices}
    await entity.async_get_tts_audio("hello", "en-US", {})
    assert aioclient_mock.call_count == 2


async def test_diagnostics(hass, configured_entry, load_capture):
    result = await async_get_config_entry_diagnostics(hass, configured_entry)
    assert result["data"]["api_key"] == "**REDACTED**"
    assert "test-key" not in str(result)
    assert result["voice_cache_size"] == len(load_capture("voices_en_us")["voices"])
    assert result["voice_cache_last_refresh"]
    subentry = next(iter(configured_entry.subentries.values()))
    assert result["subentries"][subentry.subentry_id]["data"] == subentry.data


async def test_unload_reload_remove(hass, configured_entry, gemini_http):
    entry = configured_entry
    client = entry.runtime_data
    initial_calls = gemini_http.call_count
    registry = er.async_get(hass)
    original_unique_id = registry.async_get("tts.alice").unique_id
    for _ in range(2):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert hass.states.get("tts.alice").state == "unavailable"
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert registry.async_get("tts.alice").unique_id == original_unique_id
        assert entry.runtime_data is client
        assert len(entry.update_listeners) == 1
    assert gemini_http.call_count == initial_calls
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert DOMAIN not in hass.data
    assert registry.async_get("tts.alice") is None


async def test_raw_pcm_via_registered_entity(entity, gemini_http):
    import base64
    import io
    import wave

    raw = b"\x01\x02" * 100
    gemini_http.clear_requests()
    gemini_http.post(
        f"{API_URL}/interactions",
        json={
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "audio",
                            "mime_type": "audio/pcm;rate=16000",
                            "data": base64.b64encode(raw).decode(),
                        }
                    ],
                }
            ]
        },
    )
    extension, result = await entity.async_get_tts_audio("hello", "en-US", {})
    assert extension == "wav"
    with wave.open(io.BytesIO(result), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
            16000,
            1,
            2,
        )
        assert wav.readframes(100) == raw


async def test_profile_device_name_is_used(hass, entity):
    assert entity.entity_id == "tts.alice"
    assert hass.states.get(entity.entity_id).attributes["friendly_name"] == "Alice"


async def test_voice_language_prefix_and_custom_voice(entity, configured_entry):
    client = configured_entry.runtime_data
    client.voices = [
        {
            "id": "en-special",
            "display_name": "English",
            "language_code": "en-US",
            "description": "A" * 60,
        },
        {
            "id": "fr-special",
            "display_name": "French",
            "language_code": "fr-FR",
            "description": "B" * 60,
        },
    ]
    english = {v.voice_id for v in entity.async_get_supported_voices("en")}
    french = {v.voice_id for v in entity.async_get_supported_voices("fr-FR")}
    assert "en-special" in english and "fr-special" not in english
    assert "fr-special" in french and "en-special" not in french
    assert len(english) == len(french) == 31
    assert "kore" in english & french
