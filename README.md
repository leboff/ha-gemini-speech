# Gemini Speech for Home Assistant

Gemini text to speech with a default **style direction** for each voice profile and overrides for individual announcements. Delivery instructions such as “warm, dry and conversational” go in `speech_metadata.style` on the Gemini Interactions API. Your message is sent verbatim, including performed inline tags such as `<short pause>` and `<chuckle>`.

This integration also handles the `audio/wav` responses that HA 2026.10.1's built-in Gemini TTS cannot play. The built-in WAV issue is fixed upstream in 2026.10.2; style direction is the reason to use Gemini Speech beyond that fix.

Each API key is an integration entry. Each voice profile under it creates one TTS entity, such as `tts.alice`. Profiles can share a key while using different voices, models, and styles.

## Install

In HACS, open **⋮ → Custom repositories**, add `https://github.com/leboff/ha-gemini-speech` as an **Integration**, then download Gemini Speech and restart Home Assistant.

For manual installation, copy `custom_components/gemini_speech` into your Home Assistant configuration's `custom_components` directory, then restart.

Targets Home Assistant 2026.10.x and Python 3.14; tested with HA 2026.10.1. HACS metadata declares 2025.6.0 per the build specification, but earlier HA releases have not been tested. No Google SDK or additional integration packages are required.

## Configure

1. Open **Settings → Devices & services → Add integration → Gemini Speech**.
2. Enter your Gemini API key. A small voice-catalog request validates it; no speech is generated during configuration.
3. Choose **Add voice profile** on the integration entry.
4. Set a name (for example **Alice**), model, voice, and optional default style direction.

The default model is `gemini-3.8-flash-tts`. The model selector also offers `gemini-3.8-flash-lite-tts` and `gemini-3.1-flash-tts-preview`, and accepts custom model IDs. The voice selector combines the cached en-US catalog with 30 multilingual voices and accepts custom voice IDs. Voice names are case-insensitive; the default is `kore`.

Use a profile's **⋮ → Reconfigure** to change its voice, model, style, or name; **Delete** removes the profile and its entity. Changes take effect without restarting HA. To replace the API key, reconfigure the main integration entry. HA preserves existing entity IDs when a profile is renamed; change an entity ID in its settings if desired.

The catalog loads at setup and refreshes on the first speech request after 24 hours. Profile reloads reuse the in-memory cache. If discovery fails, cached voices and the 30 static multilingual voices remain available. Language is detected automatically from the text; the HA language selector filters voice discovery.

## Announcements

Use **Developer tools → Actions** or your own automations. Replace the media player and TTS entity IDs with yours.

Use the profile defaults:

```yaml
action: tts.speak
target:
  entity_id: tts.alice
data:
  media_player_entity_id: media_player.living_room
  message: "Morning. <short pause> Rain at four. <chuckle>"
```

Override the voice, style, and model for one call:

```yaml
action: tts.speak
target:
  entity_id: tts.alice
data:
  media_player_entity_id: media_player.living_room
  message: "The laundry is ready."
  options:
    voice: puck
    style: "bright, upbeat and brief"
    model: gemini-3.8-flash-lite-tts
```

An explicit empty style disables the profile's default direction for that call:

```yaml
action: tts.speak
target:
  entity_id: tts.alice
data:
  media_player_entity_id: media_player.living_room
  message: "The front door is open."
  options:
    style: ""
```

## Inline tag cheat sheet

| Tag | Delivery cue |
| --- | --- |
| `<short pause>` | Brief pause |
| `<chuckle>` | Small laugh |
| `<tsk>` | Tongue-click expression |

These tags were checked with the captured Gemini 3.8 speech examples. Delivery can vary by model and voice. Place delivery direction in the style field; text in the message is spoken verbatim except for model-supported performance tags.

## Behavior and troubleshooting

- Unary synthesis only: the full response is downloaded before playback. The integration returns WAV bytes unchanged. Raw `audio/l16` or `audio/pcm` responses receive a WAV header without transcoding. HA may subsequently convert the audio for a player or add cache metadata.
- Requests time out after 120 seconds. API errors include Google's message; failures are raised to HA. If key validation fails, check the key and its access to the voice catalog.
- Messages over 4,000 characters produce a warning and are sent unchanged. Gemini may truncate them; this version does not split messages.
- HA's TTS cache can reuse an announcement. Use `cache: false` while comparing delivery styles.
- Diagnostics include redacted entry data, voice profiles, catalog size, and the last catalog refresh attempt. Keys, messages, and audio are not logged by this integration.

## Development

Tests use mocked HTTP and the real API captures under `tests/fixtures/`; they do not call Gemini. Do not edit those JSON captures or run `tools/capture_fixtures.py` during offline development.

```sh
python -m pytest -q
python -m compileall -q custom_components tests
```

A minimal HA test environment also needs HA's own TTS dependencies (`mutagen==1.48.1` and `ha-ffmpeg==3.2.2` for HA 2026.10.1). These belong to HA, not this integration's empty requirements list.

The validation workflow runs HACS and hassfest. Publishing and release creation happen separately after review. See [NOTES_FOR_REVIEW.md](NOTES_FOR_REVIEW.md) for implementation decisions and validation limits.

MIT license, Bryan Leboff.
