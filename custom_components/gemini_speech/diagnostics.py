"""Diagnostics without credentials or synthesized messages/audio."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import GeminiSpeechConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GeminiSpeechConfigEntry
) -> dict:
    """Return redacted config, profiles, and catalog status."""
    client = getattr(entry, "runtime_data", None)
    return {
        "data": async_redact_data(dict(entry.data), {CONF_API_KEY}),
        "subentries": {
            subentry.subentry_id: {"title": subentry.title, "data": dict(subentry.data)}
            for subentry in entry.subentries.values()
        },
        "voice_cache_size": len(client.voices) if client else 0,
        "voice_cache_last_refresh": client.last_refresh.isoformat()
        if client and client.last_refresh
        else None,
    }
