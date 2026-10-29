"""Offline smoke tests: external models/APIs are replaced by stand-ins so these run anywhere.
Run:  pytest -q
(The real-model check is tests/roundtrip.py, run against a live server.)
"""
import io
import json
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod  # noqa: E402
from services import langs, llm, store, stt, tts  # noqa: E402


def wav_bytes(n=4000):
    """A valid (silent) WAV so the magic-byte check passes."""
    data = b"\x00\x00" * n
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
    return hdr + b"data" + struct.pack("<I", len(data)) + data


def png_bytes():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 20)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(appmod, "RATE_PER_MIN", 0)
    seen = {}

    def fake_reply(text, lang, history=None, tool_result=None, image=None):
        seen.update(text=text, lang=lang, history=history, tool=tool_result, image=image)
        return {"hi": "आज मौसम साफ़ है।", "bn": "আজ আবহাওয়া পরিষ্কার।", "or": "ଆଜି ପାଣିପାଗ ସ୍ୱଚ୍ଛ।"}.get(lang, "It is clear.")

    monkeypatch.setattr(llm, "reply", fake_reply)
    monkeypatch.setattr(llm, "reply_stream", lambda *a, **k: iter(["आज ", "मौसम ", "साफ़ है।"]))
    monkeypatch.setattr(llm, "route_intent", lambda text, lang: {"intent": "chat", "city": None})
    monkeypatch.setattr(llm, "translate", lambda text, target, source=None: f"[{target}] {text}")
    monkeypatch.setattr(tts, "synthesize", lambda text, lang: (wav_bytes(), "audio/wav", "fake-mms"))
    monkeypatch.setattr(stt, "transcribe", lambda audio, filename="a.webm", language=None:
                        {"text": "आज मौसम कैसा है?", "language": "hi", "backend": "fake", "duration_ms": 5})
    c = appmod.app.test_client()
    c.seen = seen
    return c


def test_health(client):
    j = client.get("/health").get_json()
    assert j["status"] == "ok" and "llm_model" in j and "stt_backend" in j


def test_languages(client):
    codes = {x["code"] for x in client.get("/api/languages").get_json()}
    assert codes == {"hi", "bn", "or", "en"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and b"Bolo" in r.data


def test_translate(client):
    r = client.post("/api/translate", json={"text": "hello", "target": "hi"})
    assert r.status_code == 200 and r.get_json()["text"] == "[hi] hello"
    bad = client.post("/api/translate", json={"text": "hello", "target": "xx"})
    assert bad.status_code == 400 and bad.get_json()["code"] == "bad_request"


def test_speak(client):
    r = client.post("/api/speak", json={"text": "नमस्ते", "lang": "hi"})
    assert r.status_code == 200 and r.mimetype == "audio/wav" and r.data[:4] == b"RIFF"
    assert r.headers["X-TTS-Backend"] == "fake-mms"
    assert client.post("/api/speak", json={"text": "x", "lang": "fr"}).status_code == 400


def test_transcribe_validation(client):
    assert client.post("/api/transcribe").status_code == 400
    r = client.post("/api/transcribe", data={"audio": (io.BytesIO(b"not audio" * 200), "x.webm")},
                    content_type="multipart/form-data")
    assert r.status_code == 415 and r.get_json()["code"] == "bad_audio"
    tiny = client.post("/api/transcribe", data={"audio": (io.BytesIO(b"RIFF"), "x.wav")},
                       content_type="multipart/form-data")
    assert tiny.status_code == 422


def test_transcribe_ok(client):
    r = client.post("/api/transcribe", data={"audio": (io.BytesIO(wav_bytes()), "a.wav")},
                    content_type="multipart/form-data")
    j = r.get_json()
    assert r.status_code == 200 and j["language"] == "hi" and j["text"]


def test_odia_voice_is_rejected_honestly():
    with pytest.raises(stt.STTError) as e:
        stt.transcribe(wav_bytes(), "a.wav", "or")
    assert e.value.code == "odia_voice_unsupported" and e.value.status == 400


def test_chat_text_hindi(client):
    r = client.post("/api/chat", data={"text": "आज मौसम कैसा है?", "session_id": "s1"})
    j = r.get_json()
    assert r.status_code == 200
    assert j["language"] == "hi" and any("ऀ" <= c <= "ॿ" for c in j["reply_text"])
    assert j["audio_b64"] and j["audio_mime"] == "audio/wav" and "timings" in j
    h = client.get("/api/history?session_id=s1").get_json()
    assert [t["role"] for t in h] == ["user", "assistant"]


def test_chat_audio_detects_language(client):
    r = client.post("/api/chat", data={"audio": (io.BytesIO(wav_bytes()), "a.wav")},
                    content_type="multipart/form-data")
    j = r.get_json()
    assert r.status_code == 200 and j["transcript"] == "आज मौसम कैसा है?" and j["language"] == "hi"


def test_chat_odia_typed_gets_odia_reply(client):
    j = client.post("/api/chat", data={"text": "ଆଜି ପାଣିପାଗ କିପରି?"}).get_json()
    assert j["language"] == "or" and "ଆଜି" in j["reply_text"]


def test_chat_odia_voice_refused_in_odia(client):
    r = client.post("/api/chat", data={"audio": (io.BytesIO(wav_bytes()), "a.wav"), "lang": "or"},
                    content_type="multipart/form-data")
    assert r.status_code == 400 and r.get_json()["code"] == "odia_voice_unsupported"
    assert any("଀" <= c <= "୿" for c in r.get_json()["user_message"])


def test_chat_with_image_reaches_model(client):
    r = client.post("/api/chat", data={"text": "इस तस्वीर में क्या है?", "image": (io.BytesIO(png_bytes()), "p.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert client.seen["image"][:2] == b"\xff\xd8"  # re-encoded as JPEG


def test_chat_needs_input(client):
    assert client.post("/api/chat", data={}).status_code == 400


def test_stream_event_order(client):
    r = client.post("/api/chat/stream", data={"text": "नमस्ते"})
    assert r.mimetype == "text/event-stream"
    names = [ln[7:] for ln in r.get_data(as_text=True).splitlines() if ln.startswith("event: ")]
    assert names[0] == "transcript" or names[:1] == ["status"] or "transcript" in names
    assert names.index("transcript") < names.index("token") < names.index("audio") < names.index("done")
    assert names.count("token") == 3


def test_pipeline_error_is_localized(client, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("quota", "llm_busy", 429)
    monkeypatch.setattr(llm, "reply", boom)
    r = client.post("/api/chat", data={"text": "नमस्ते"})
    j = r.get_json()
    assert r.status_code == 429 and j["code"] == "llm_busy" and j["user_message"] == langs.msg("busy", "hi")


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(appmod, "RATE_PER_MIN", 2)
    appmod._buckets.clear()
    codes = [client.get("/api/languages").status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes


def test_unit_language_helpers():
    assert langs.detect_script("ওড়িয়া নয়, বাংলা") == "bn"
    assert langs.detect_script("hello") is None
    assert appmod.pick_language(None, "नमस्ते", "ur") == "hi"       # Whisper mislabels Hindi as Urdu
    assert appmod.pick_language(None, "namaste", "hi") == "hi"      # romanised Hindi -> trust Whisper
    assert appmod.pick_language("bn", "नमस्ते", "hi") == "bn"       # pinned choice wins
    assert appmod.pick_language(None, "hello", "fr") == "en"


def test_unit_tts_text_helpers():
    assert tts.clean_text("**नमस्ते** 😀 देखें https://x.y #टैग") == "नमस्ते देखें टैग"
    chunks = tts.split_sentences("पहला वाक्य। दूसरा वाक्य? तीसरा!", limit=20)
    assert len(chunks) >= 2 and all(len(c) <= 40 for c in chunks)
    assert tts.split_sentences("") == []


def test_sniff_audio():
    assert appmod.sniff_audio(wav_bytes()) == "wav"
    assert appmod.sniff_audio(b"\x1a\x45\xdf\xa3" + b"0" * 20) == "webm"
    assert appmod.sniff_audio(b"\x00\x00\x00\x18ftypmp42" + b"0" * 20) == "m4a"
    assert appmod.sniff_audio(b"<html>") is None
