"""Exercise key and profile flows through HA's flow managers."""

import aiohttp
import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.gemini_speech.config_flow import key_unique_id
from custom_components.gemini_speech.const import API_URL, DEFAULT_MODEL, DOMAIN

PROFILE = {"name": "Alice", "model": DEFAULT_MODEL, "voice": "kore", "style": "warm"}


async def test_user_and_duplicate(hass, gemini_http):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"].schema["api_key"].config["type"] == "password"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "test-key"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gemini Speech"
    assert result["data"] == {"api_key": "test-key"}
    await hass.async_block_till_done()
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == key_unique_id("test-key")
    assert len(entry.unique_id) == 32
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"api_key": "test-key"}
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_invalid_key(hass, aioclient_mock, load_capture, status):
    aioclient_mock.get(
        f"{API_URL}/voices", status=status, json=load_capture("err_bad_key")["response"]
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"api_key": "invalid"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_network_error(hass, aioclient_mock):
    aioclient_mock.get(f"{API_URL}/voices", exc=aiohttp.ClientConnectionError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"api_key": "test-key"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_key(hass, configured_entry, gemini_http):
    old_client = configured_entry.runtime_data
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": configured_entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_key": "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert configured_entry.data == {"api_key": "new-key"}
    assert configured_entry.unique_id == key_unique_id("new-key")
    assert configured_entry.runtime_data is not old_client
    assert configured_entry.runtime_data.matches_key("new-key")
    assert hass.states.get("tts.alice") is not None


async def test_profile_add_reconfigure_delete(hass, gemini_http):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"api_key": "test-key"}
    )
    await hass.async_block_till_done()
    entry = result["result"]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "tts"), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], PROFILE
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    subentry = next(iter(entry.subentries.values()))
    assert hass.states.get("tts.alice") is not None
    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get("tts.alice")
    assert entity.unique_id == subentry.subentry_id
    assert entity.config_subentry_id == subentry.subentry_id
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device.name == "Alice"
    assert device.manufacturer == "Google"
    assert device.model == DEFAULT_MODEL
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    client = entry.runtime_data
    catalog_calls = [
        call for call in gemini_http.mock_calls if call[1].path.endswith("/voices")
    ]
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "tts"),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**PROFILE, "voice": "puck", "style": "dry"}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.runtime_data is client
    from homeassistant.components.tts.const import DATA_COMPONENT

    tts_entity = hass.data[DATA_COMPONENT].get_entity("tts.alice")
    assert tts_entity.default_options["voice"] == "puck"
    assert tts_entity.default_options["style"] == "dry"
    await tts_entity.async_get_tts_audio("Hello", "en-US", {})
    assert gemini_http.mock_calls[-1][2]["generation_config"]["speech_config"] == [
        {"voice": "puck"}
    ]
    assert (
        gemini_http.mock_calls[-1][2]["input"][0]["content"][0]["annotations"][0][
            "style"
        ]
        == "dry"
    )
    assert [
        call for call in gemini_http.mock_calls if call[1].path.endswith("/voices")
    ] == catalog_calls
    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    await hass.async_block_till_done()
    assert hass.states.get("tts.alice") is None
    assert entity_registry.async_get("tts.alice") is None


async def test_reconfigure_revalidates_and_preserves_old_key(
    hass, configured_entry, gemini_http, load_capture
):
    gemini_http.clear_requests()
    gemini_http.get(
        f"{API_URL}/voices", status=400, json=load_capture("err_bad_key")["response"]
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": configured_entry.entry_id},
        data={"api_key": "invalid"},
    )
    assert result["errors"] == {"base": "invalid_auth"}
    assert configured_entry.data["api_key"] == "test-key"
    assert configured_entry.unique_id == key_unique_id("test-key")


async def test_reconfigure_cannot_duplicate_another_key(
    hass, configured_entry, gemini_http
):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(
        domain=DOMAIN,
        data={"api_key": "other-key"},
        unique_id=key_unique_id("other-key"),
    )
    other.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": configured_entry.entry_id},
        data={"api_key": "other-key"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert configured_entry.data["api_key"] == "test-key"
