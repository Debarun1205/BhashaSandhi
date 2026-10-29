"""Speech to text with Whisper (open weights, MIT license).

Backends
  groq  - Whisper large-v3 hosted by Groq (fast, needs GROQ_API_KEY)
  local - faster-whisper running the same family of weights on CPU (no key)
  auto  - groq when a key is present, otherwise local
"""
from __future__ import annotations

import logging
import os
import threading
import time

import requests

from . import langs

log = logging.getLogger("stt")

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")

# Whisper tends to hallucinate these on silence / background noise.
HALLUCINATIONS = {
    "thank you", "thanks for watching", "thank you for watching", "you", "bye", ".",
    "subtitles by the amara.org community", "धन्यवाद", "ধন্যবাদ",
}

_local_model = None
_local_lock = threading.Lock()


class STTError(Exception):
    def __init__(self, message: str, code: str = "stt_error", status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status


def backend_name() -> str:
    choice = os.getenv("STT_BACKEND", "auto").lower()
    if choice == "auto":
        return "groq" if os.getenv("GROQ_API_KEY") else "local"
    return choice


def _groq(audio: bytes, filename: str, language: str | None) -> dict:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise STTError("GROQ_API_KEY is not set", "no_stt_key", 503)
    data = {"model": GROQ_MODEL, "response_format": "verbose_json", "temperature": "0"}
    if language:
        data["language"] = language
    try:
        r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                          files={"file": (filename, audio)}, data=data, timeout=60)
    except requests.RequestException as exc:
        raise STTError(f"Groq unreachable: {exc}", "stt_unreachable", 502) from exc
    if r.status_code == 429:
        raise STTError("Speech service is rate limited", "stt_busy", 429)
    if not r.ok:
        raise STTError(f"Groq error {r.status_code}: {r.text[:200]}", "stt_error", 502)
    j = r.json()
    return {"text": (j.get("text") or "").strip(), "language": langs.normalize_code(j.get("language"))}


def _load_local():
    global _local_model
    with _local_lock:
        if _local_model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise STTError("faster-whisper is not installed", "no_local_stt", 503) from exc
            size = os.getenv("WHISPER_LOCAL_MODEL", "small")
            log.info("Loading local faster-whisper model '%s' ...", size)
            _local_model = WhisperModel(size, device="cpu", compute_type="int8")
    return _local_model


def _local(audio: bytes, filename: str, language: str | None) -> dict:
    import io
    model = _load_local()
    segments, info = model.transcribe(io.BytesIO(audio), language=language, vad_filter=True, beam_size=1)
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": langs.normalize_code(info.language)}


def transcribe(audio: bytes, filename: str = "audio.webm", language: str | None = None) -> dict:
    """Return {text, language, backend, duration_ms}. Raises STTError."""
    language = langs.normalize_code(language)
    if language and not langs.LANGS.get(language, {}).get("stt"):
        if language == "or":
            raise STTError("Whisper does not support Odia speech.", "odia_voice_unsupported", 400)
        language = None  # unknown hint: let Whisper auto-detect
    backend = backend_name()
    started = time.time()
    result = (_groq if backend == "groq" else _local)(audio, filename, language)
    text = result["text"]
    if not text or text.lower().strip(" .!") in HALLUCINATIONS or not langs.has_letters(text):
        raise STTError("No speech detected", "no_speech", 422)
    result.update(backend=f"whisper-large-v3 via groq" if backend == "groq" else f"faster-whisper-{os.getenv('WHISPER_LOCAL_MODEL', 'small')}",
                  duration_ms=int((time.time() - started) * 1000))
    return result
