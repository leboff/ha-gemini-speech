"""Gemini Speech: style-directed text to speech over the Interactions API."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GeminiSpeechClient
from .const import DOMAIN

PLATFORMS = [Platform.TTS]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
type GeminiSpeechConfigEntry = ConfigEntry[GeminiSpeechClient]


async def async_setup_entry(
    hass: HomeAssistant, entry: GeminiSpeechConfigEntry
) -> bool:
    """Set up the shared client, catalog, and profile entities."""
    # HA deletes runtime_data on unload; retain only the passive client/cache for reload.
    clients = hass.data.setdefault(DOMAIN, {})
    client = clients.get(entry.entry_id)
    if client is None or not client.matches_key(entry.data[CONF_API_KEY]):
        client = GeminiSpeechClient(
            async_get_clientsession(hass), entry.data[CONF_API_KEY]
        )
    clients[entry.entry_id] = client
    entry.runtime_data = client
    # Don't block HA startup on paging the voice catalog; the static list covers the gap.
    entry.async_create_background_task(hass, client.refresh_voices(), "gemini_speech_voice_catalog")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(
    hass: HomeAssistant, entry: GeminiSpeechConfigEntry
) -> None:
    """Reload when credentials or voice profiles are added, edited, or removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: GeminiSpeechConfigEntry
) -> bool:
    """Unload entities; the HTTP session belongs to Home Assistant."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: GeminiSpeechConfigEntry
) -> None:
    """Discard the passive voice cache when its API key entry is deleted."""
    clients = hass.data.get(DOMAIN, {})
    clients.pop(entry.entry_id, None)
    if not clients:
        hass.data.pop(DOMAIN, None)
