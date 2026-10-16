"""Exercise the captured API formats and lossless WAV handling."""

import base64
import io
import wave
from copy import deepcopy

import pytest

from custom_components.gemini_speech.audio import ensure_wav, extract_audio, parse_error


@pytest.mark.parametrize("name", ["ok_plain", "ok_lite", "ok_style_tags"])
def test_extract_capture(load_capture, name):
    mime, data = extract_audio(load_capture(name)["response"])
    assert mime == "audio/wav"
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    assert ensure_wav(mime, data) == data


def test_last_audio_and_only_model_output(load_capture):
    response = deepcopy(load_capture("ok_plain")["response"])
    original = extract_audio(response)
    response["steps"][0]["content"].append(
        {
            "type": "audio",
            "mime_type": "audio/pcm",
            "data": base64.b64encode(b"last").decode(),
        }
    )
    assert extract_audio(response) == ("audio/pcm", b"last")
    response["steps"].append(load_capture("ok_lite")["response"]["steps"][0])
    assert extract_audio(response) == extract_audio(load_capture("ok_lite")["response"])
    response["steps"][-1]["type"] = "user_input"
    assert extract_audio(response) != original
    assert extract_audio(response) == ("audio/pcm", b"last")


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"steps": []},
        {"steps": [{"type": "user_input", "content": [{"type": "audio"}]}]},
    ],
)
def test_no_audio(response):
    with pytest.raises(ValueError, match="Gemini returned no audio"):
        extract_audio(response)


@pytest.mark.parametrize(
    "mime,rate",
    [("audio/l16", 24000), ("audio/pcm", 24000), ("audio/l16;rate=16000", 16000)],
)
def test_raw_pcm_header(mime, rate):
    pcm = b"\x01\x02" * 100
    result = ensure_wav(mime, pcm)
    assert len(result) == 44 + len(pcm)
    with wave.open(io.BytesIO(result), "rb") as wav:
        assert wav.getframerate() == rate
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(100) == pcm


def test_unsupported_mime():
    with pytest.raises(ValueError, match="Unsupported audio MIME type"):
        ensure_wav("audio/mpeg", b"audio")


@pytest.mark.parametrize("name", ["err_bad_key", "err_bad_voice", "err_bad_model"])
def test_error_captures(load_capture, name):
    capture = load_capture(name)
    error = capture["response"]
    expected = (error[0] if isinstance(error, list) else error)["error"]["message"]
    assert parse_error(capture["status"], error) == expected


def test_non_json_error():
    assert parse_error(502, b"Bad gateway") == "Bad gateway"
    assert parse_error(503, "") == "HTTP 503"
