"""API key configuration and independently configurable TTS profiles."""

import hashlib
from typing import Any

try:  # Match ha-wled-alerts: HA 2026.9+ uses probatio with the same schema API.
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, GeminiSpeechClient, GeminiSpeechError
from .const import (
    CONF_MODEL,
    CONF_STYLE,
    CONF_VOICE,
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    DOMAIN,
    MODELS,
    NAME,
    STATIC_VOICES,
    SUBENTRY_TTS,
)

KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
)


def key_unique_id(api_key: str) -> str:
    """Use the first 128 bits of SHA-256, never credentials, as the unique ID."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:32]


class GeminiSpeechConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one API key, then add voice profiles as subentries."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add an API key."""
        return await self._async_key_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Revalidate and replace the key."""
        return await self._async_key_step("reconfigure", user_input)

    async def _async_key_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            unique_id = key_unique_id(user_input[CONF_API_KEY])
            await self.async_set_unique_id(unique_id)
            current = (
                self._get_reconfigure_entry() if step_id == "reconfigure" else None
            )
            if any(
                entry.unique_id == unique_id and entry is not current
                for entry in self._async_current_entries()
            ):
                return self.async_abort(reason="already_configured")
            client = GeminiSpeechClient(
                async_get_clientsession(self.hass), user_input[CONF_API_KEY]
            )
            try:
                await client.validate_key()
            except AuthError:
                errors["base"] = "invalid_auth"
            except GeminiSpeechError:
                errors["base"] = "cannot_connect"
            else:
                if current is not None:
                    if current.update_listeners:
                        return self.async_update_and_abort(
                            current, unique_id=unique_id, data=user_input
                        )
                    return self.async_update_reload_and_abort(
                        current, unique_id=unique_id, data=user_input
                    )
                return self.async_create_entry(title=NAME, data=user_input)
        return self.async_show_form(
            step_id=step_id, data_schema=KEY_SCHEMA, errors=errors
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Offer a profile for each independent voice/style/model combination."""
        return {SUBENTRY_TTS: TtsSubentryFlow}


class TtsSubentryFlow(ConfigSubentryFlow):
    """Add and reconfigure a single voice profile."""

    def _schema(self, defaults: dict[str, Any]) -> vol.Schema:
        entry = self._get_entry()
        client = getattr(entry, "runtime_data", None)
        current_voice = defaults.get(CONF_VOICE, DEFAULT_VOICE)
        if client is not None:
            voices = client.supported_voices("en-US", current_voice)
        else:
            voices = {**STATIC_VOICES}
            voices.setdefault(current_voice, current_voice)
        return self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(CONF_NAME): selector.TextSelector(),
                    vol.Required(
                        CONF_MODEL, default=DEFAULT_MODEL
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=MODELS,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_VOICE, default=DEFAULT_VOICE
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=voice_id, label=label)
                                for voice_id, label in voices.items()
                            ],
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_STYLE): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                }
            ),
            defaults,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a profile (no paid synthesis request is made here)."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME], data=dict(user_input)
            )
        return self.async_show_form(step_id="user", data_schema=self._schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a profile and trigger the entry update listener."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data=dict(user_input),
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._schema({**subentry.data, CONF_NAME: subentry.title}),
        )
