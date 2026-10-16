"""One unary text-to-speech entity per voice profile."""

import logging
from typing import Any, ClassVar

from homeassistant.components.tts import TextToSpeechEntity, TtsAudioType, Voice
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GeminiSpeechConfigEntry
from .api import GeminiSpeechError
from .const import (
    CONF_MODEL,
    CONF_STYLE,
    CONF_VOICE,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    DOMAIN,
    SUBENTRY_TTS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GeminiSpeechConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Attach entities to their subentries, so HA handles removal correctly."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_TTS:
            async_add_entities(
                [GeminiSpeechEntity(entry, subentry)],
                config_subentry_id=subentry.subentry_id,
            )


class GeminiSpeechEntity(TextToSpeechEntity):
    """Gemini voice profile with per-call delivery overrides."""

    _attr_has_entity_name = True
    # HA 2026.10.1 TTS rejects None; empty still inherits the profile device name.
    _attr_name = ""
    _attr_default_language = "en-US"
    _attr_supported_options: ClassVar[list[str]] = [CONF_VOICE, CONF_STYLE, CONF_MODEL]
    # Copied from HA 2026.10.1 google_generative_ai_conversation/tts.py, plus UK/AU.
    _attr_supported_languages: ClassVar[list[str]] = [
        "af-ZA",
        "am-ET",
        "ar-EG",
        "az-AZ",
        "be-BY",
        "bg-BG",
        "bn-BD",
        "ca-ES",
        "ceb-PH",
        "cmn-CN",
        "cs-CZ",
        "da-DK",
        "de-DE",
        "el-GR",
        "en-IN",
        "en-US",
        "es-ES",
        "es-US",
        "et-EE",
        "eu-ES",
        "fa-IR",
        "fi-FI",
        "fil-PH",
        "fr-FR",
        "gl-ES",
        "gu-IN",
        "he-IL",
        "hi-IN",
        "hr-HR",
        "ht-HT",
        "hu-HU",
        "hy-AM",
        "id-ID",
        "is-IS",
        "it-IT",
        "ja-JP",
        "jv-ID",
        "ka-GE",
        "kn-IN",
        "ko-KR",
        "kok-IN",
        "la-VA",
        "lb-LU",
        "lo-LA",
        "lt-LT",
        "lv-LV",
        "mai-IN",
        "mg-MG",
        "mk-MK",
        "ml-IN",
        "mn-MN",
        "mr-IN",
        "ms-MY",
        "my-MM",
        "nb-NO",
        "ne-NP",
        "nl-NL",
        "nn-NO",
        "or-IN",
        "pa-IN",
        "pl-PL",
        "ps-AF",
        "pt-BR",
        "pt-PT",
        "ro-RO",
        "ru-RU",
        "sd-PK",
        "si-LK",
        "sk-SK",
        "sl-SI",
        "sq-AL",
        "sr-RS",
        "sv-SE",
        "sw-KE",
        "ta-IN",
        "te-IN",
        "th-TH",
        "tr-TR",
        "uk-UA",
        "ur-PK",
        "vi-VN",
        "en-GB",
        "en-AU",
    ]

    def __init__(
        self, entry: GeminiSpeechConfigEntry, subentry: ConfigSubentry
    ) -> None:
        self._client = entry.runtime_data
        self._attr_unique_id = subentry.subentry_id
        self._attr_default_options = {
            CONF_VOICE: subentry.data.get(CONF_VOICE, DEFAULT_VOICE),
            CONF_STYLE: subentry.data.get(CONF_STYLE, ""),
            CONF_MODEL: subentry.data.get(CONF_MODEL, DEFAULT_MODEL),
        }
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Google",
            model=self._attr_default_options[CONF_MODEL],
            entry_type=DeviceEntryType.SERVICE,
        )

    @callback
    def async_get_supported_voices(self, language: str) -> list[Voice]:
        """Use the cached language catalog plus multilingual and custom voices."""
        return [
            Voice(voice_id, label)
            for voice_id, label in self._client.supported_voices(
                language, self._attr_default_options[CONF_VOICE]
            ).items()
        ]

    async def async_get_tts_audio(
        self, message: str, language: str, options: dict[str, Any]
    ) -> TtsAudioType:
        """Send text unchanged; an explicit empty style suppresses metadata."""
        if len(message) > 4000:
            _LOGGER.warning(
                "Gemini TTS message exceeds 4,000 characters and may be truncated"
            )
        resolved = {**self._attr_default_options, **options}
        try:
            audio = await self._client.synthesize(
                message,
                resolved[CONF_VOICE],
                resolved[CONF_STYLE],
                resolved[CONF_MODEL],
            )
        except GeminiSpeechError as err:
            raise HomeAssistantError(str(err)) from err
        return "wav", audio
