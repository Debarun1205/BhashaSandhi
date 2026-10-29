"""Text to speech with Meta MMS-TTS (open weights, VITS) for Hindi, Bengali and Odia.

Fallback chain: MMS-TTS -> gTTS (hi/bn/en only, needs internet) -> error (the browser then
falls back to its own speechSynthesis).
"""
from __future__ import annotations

import io
import logging
import os
import re
import threading
from collections import OrderedDict

import numpy as np

from . import langs

log = logging.getLogger("tts")

MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "600"))
_models: dict = {}
_lock = threading.Lock()
_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
_CACHE_SIZE = 64


class TTSError(Exception):
    def __init__(self, message: str, code: str = "tts_error", status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status


# ---------- text preparation ----------
_MD = re.compile(r"[*_`#>~|]+")
_URL = re.compile(r"https?://\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def clean_text(text: str) -> str:
    """Strip markdown/emoji/links so the voice never reads out symbols."""
    text = _URL.sub(" ", text)
    text = _EMOJI.sub(" ", text)
    text = _MD.sub(" ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str, limit: int = 180) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[।॥.?!])\s+", text) if p.strip()]
    chunks, cur = [], ""
    for p in parts:
        while len(p) > limit:  # very long sentence: break on commas / spaces
            cut = max(p.rfind(",", 0, limit), p.rfind(" ", 0, limit))
            cut = cut if cut > 20 else limit
            chunks.append(p[:cut].strip())
            p = p[cut:].strip(" ,")
        if cur and len(cur) + len(p) + 1 > limit:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        chunks.append(cur)
    return chunks


# ---------- MMS backend ----------
def _load(lang: str):
    code = langs.LANGS[lang]["mms"]
    with _lock:
        if lang not in _models:
            try:
                import torch  # noqa: F401
                from transformers import AutoTokenizer, VitsModel
            except ImportError as exc:
                raise TTSError("transformers/torch not installed", "no_mms", 503) from exc
            repo = f"facebook/mms-tts-{code}"
            log.info("Loading %s ...", repo)
            tok = AutoTokenizer.from_pretrained(repo)
            model = VitsModel.from_pretrained(repo).eval()
            _models[lang] = (tok, model)
    return _models[lang]


def preload(codes: list[str]) -> None:
    for c in codes:
        try:
            _load(c)
            log.info("Preloaded TTS for %s", c)
        except Exception as exc:  # preload must never crash the server
            log.warning("Preload %s failed: %s", c, exc)


def loaded() -> list[str]:
    return sorted(_models)


def _wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    from scipy.io import wavfile
    pcm = np.clip(samples, -1.0, 1.0)
    buf = io.BytesIO()
    wavfile.write(buf, rate, (pcm * 32767).astype(np.int16))
    return buf.getvalue()


def _mms(text: str, lang: str) -> bytes:
    import torch
    tok, model = _load(lang)
    rate = model.config.sampling_rate
    pieces, gap = [], np.zeros(int(rate * 0.25), dtype=np.float32)
    for chunk in split_sentences(text):
        inputs = tok(chunk, return_tensors="pt")
        if inputs["input_ids"].shape[-1] == 0:
            continue
        torch.manual_seed(555)  # VITS is stochastic; fixed seed = same voice every time
        with torch.no_grad():
            wave = model(**inputs).waveform[0].cpu().numpy().astype(np.float32)
        pieces += [wave, gap]
    if not pieces:
        raise TTSError("Nothing speakable in text", "empty_text", 422)
    return _wav_bytes(np.concatenate(pieces[:-1]), rate)


# ---------- gTTS fallback ----------
def _gtts(text: str, lang: str) -> bytes:
    code = langs.LANGS[lang]["gtts"]
    if not code:
        raise TTSError(f"gTTS cannot speak {lang}", "no_fallback", 503)
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        gTTS(text=text, lang=code).write_to_fp(buf)
        return buf.getvalue()
    except Exception as exc:
        raise TTSError(f"gTTS failed: {exc}", "tts_unreachable", 502) from exc


def synthesize(text: str, lang: str) -> tuple[bytes, str, str]:
    """Return (audio_bytes, mime, backend_name)."""
    if lang not in langs.LANGS or not langs.LANGS[lang]["tts"]:
        raise TTSError(f"Unsupported language '{lang}'", "unsupported_lang", 400)
    text = clean_text(text)[:MAX_CHARS]
    if not text:
        raise TTSError("Empty text", "empty_text", 400)
    key = (lang, text)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    result = None
    if langs.LANGS[lang]["mms"] and os.getenv("TTS_BACKEND", "auto") != "gtts":
        try:
            result = (_mms(text, lang), "audio/wav", f"facebook/mms-tts-{langs.LANGS[lang]['mms']}")
        except TTSError as exc:
            if exc.code == "empty_text":
                raise
            log.warning("MMS failed (%s), trying gTTS", exc)
        except Exception as exc:
            log.warning("MMS crashed (%s), trying gTTS", exc)
    if result is None:
        result = (_gtts(text, lang), "audio/mpeg", "gtts-fallback")
    _cache[key] = result
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return result
