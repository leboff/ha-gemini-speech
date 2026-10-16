"""Capture real Gemini Interactions-API responses as test fixtures (audio truncated so fixtures stay small but valid).

Run: GOOGLE_API_KEY=... python3 tools/capture_fixtures.py
The fixtures under tests/fixtures/ are the source of truth for the tests. Do not hand-edit them.
"""
import base64, json, os, struct, urllib.error, urllib.request
from pathlib import Path

KEY = os.environ["GOOGLE_API_KEY"]
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://generativelanguage.googleapis.com/v1beta"


def post(body, key=KEY):
    req = urllib.request.Request(f"{URL}/interactions", data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        return 200, json.load(urllib.request.urlopen(req, timeout=120))
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode()


def shrink_wav(b64: str, keep_bytes: int = 4800) -> str:
    """Keep the RIFF header + first 0.1 s of PCM, rewrite the size fields so it stays a valid WAV."""
    raw = base64.b64decode(b64)
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE", raw[:16]
    data_idx = raw.index(b"data")
    header = bytearray(raw[: data_idx + 8])
    pcm = raw[data_idx + 8 : data_idx + 8 + keep_bytes]
    struct.pack_into("<I", header, data_idx + 4, len(pcm))
    struct.pack_into("<I", header, 4, len(header) - 8 + len(pcm))
    return base64.b64encode(bytes(header) + pcm).decode()


def body(text, voice="Kore", style=None, model="gemini-3.8-flash-tts", **extra):
    item = {"type": "text", "text": text}
    if style:
        item["annotations"] = [{"type": "speech_metadata", "style": style}]
    b = {"model": model, "input": [{"type": "user_input", "content": [item]}],
         "response_format": {"type": "audio"}, "generation_config": {"speech_config": [{"voice": voice}]}}
    b.update(extra)
    return b


cases = {
    "ok_style_tags": body("Morning. <short pause> Rain at four. <chuckle>", style="warm, dry and conversational"),
    "ok_plain": body("Hello there."),
    "ok_lite": body("Hello there.", model="gemini-3.8-flash-lite-tts"),
    "err_bad_voice": body("Hello.", voice="Nope"),
    "err_bad_model": body("Hello.", model="gemini-0-nope-tts"),
}
for name, b in cases.items():
    code, resp = post(b)
    if code == 200:
        for s in resp.get("steps", []):
            for c in s.get("content", []):
                if c.get("type") == "audio":
                    c["data"] = shrink_wav(c["data"])
    (OUT / f"{name}.json").write_text(json.dumps({"request": b, "status": code, "response": resp}, indent=1))
    print(name, code)

code, resp = post(body("Hello."), key="AIzaInvalidKeyForFixture")
(OUT / "err_bad_key.json").write_text(json.dumps({"request": body("Hello."), "status": code, "response": resp}, indent=1))
print("err_bad_key", code)

# voice catalog: first page of en-US prebuilt voices (for the voice selector)
req = urllib.request.Request(f"{URL}/voices?type=prebuilt&language_code=en-US&page_size=40", headers={"x-goog-api-key": KEY})
(OUT / "voices_en_us.json").write_text(json.dumps(json.load(urllib.request.urlopen(req, timeout=30)), indent=1))
print("voices_en_us ok")
