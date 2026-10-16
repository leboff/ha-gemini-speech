"""Constants for Gemini Speech."""

DOMAIN = "gemini_speech"
NAME = "Gemini Speech"
API_URL = "https://generativelanguage.googleapis.com/v1beta"
CONF_MODEL = "model"
CONF_VOICE = "voice"
CONF_STYLE = "style"
DEFAULT_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "kore"
MODELS = [DEFAULT_MODEL, "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview"]
SUBENTRY_TTS = "tts"
REQUEST_TIMEOUT = 120
VOICE_CACHE_SECONDS = 24 * 60 * 60

# The multilingual prebuilt voices also work when catalog discovery is unavailable.
STATIC_VOICES = {
    name.split(" ", 1)[0].lower(): name
    for name in (
        "Zephyr (Bright)",
        "Puck (Upbeat)",
        "Charon (Informative)",
        "Kore (Firm)",
        "Fenrir (Excitable)",
        "Leda (Youthful)",
        "Orus (Firm)",
        "Aoede (Breezy)",
        "Callirrhoe (Easy-going)",
        "Autonoe (Bright)",
        "Enceladus (Breathy)",
        "Iapetus (Clear)",
        "Umbriel (Easy-going)",
        "Algieba (Smooth)",
        "Despina (Smooth)",
        "Erinome (Clear)",
        "Algenib (Gravelly)",
        "Rasalgethi (Informative)",
        "Laomedeia (Upbeat)",
        "Achernar (Soft)",
        "Alnilam (Firm)",
        "Schedar (Even)",
        "Gacrux (Mature)",
        "Pulcherrima (Forward)",
        "Achird (Friendly)",
        "Zubenelgenubi (Casual)",
        "Vindemiatrix (Gentle)",
        "Sadachbia (Lively)",
        "Sadaltager (Knowledgeable)",
        "Sulafat (Warm)",
    )
}
