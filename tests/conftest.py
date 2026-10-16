"""Offline fixtures for the Gemini Speech integration."""

import json
from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom integrations from this repository, as in ha-wled-alerts."""
    yield


@pytest.fixture
def load_capture():
    """Read the immutable API captures without modifying them."""

    def load(name):
        return json.loads(
            (Path(__file__).parent / "fixtures" / f"{name}.json").read_text()
        )

    return load


@pytest.fixture
def gemini_http(aioclient_mock, load_capture):
    """Serve both catalog pages and speech from real API captures."""
    from custom_components.gemini_speech.const import API_URL

    catalog = load_capture("voices_en_us")
    # Register specific query matches first; the mock otherwise matches any query.
    aioclient_mock.get(
        f"{API_URL}/voices?page_size=1", json={"voices": catalog["voices"][:1]}
    )
    aioclient_mock.get(
        f"{API_URL}/voices?page_token={catalog['next_page_token']}", json={"voices": []}
    )
    aioclient_mock.get(f"{API_URL}/voices", json=catalog)
    aioclient_mock.post(
        f"{API_URL}/interactions", json=load_capture("ok_style_tags")["response"]
    )
    return aioclient_mock


@pytest.fixture
async def configured_entry(hass, gemini_http):
    """Load one API key and its Alice profile via HA setup."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.gemini_speech.config_flow import key_unique_id
    from custom_components.gemini_speech.const import DEFAULT_MODEL, DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Gemini Speech",
        data={"api_key": "test-key"},
        unique_id=key_unique_id("test-key"),
        subentries_data=[
            {
                "subentry_type": "tts",
                "title": "Alice",
                "unique_id": None,
                "data": {
                    "name": "Alice",
                    "voice": "kore",
                    "model": DEFAULT_MODEL,
                    "style": "warm, dry and conversational",
                },
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
