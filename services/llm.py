"""Gemma 4 through the Gemini API: translation, intent routing, replies, image Q&A, streaming.

Gemma is open-weight; here we call it via the Gemini API (google-genai SDK).
Instructions are placed in the prompt (not `system_instruction`) because that works for every
Gemma model served by the API.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
from typing import Iterator

from . import langs
from .tts import clean_text

log = logging.getLogger("llm")

PRIMARY = os.getenv("GEMMA_MODEL", "gemma-4-26b-a4b-it")
FALLBACKS = ["gemma-4-31b-it", "gemma-4-26b-a4b-it"]
_client = None
_active_model: str | None = None


class LLMError(Exception):
    def __init__(self, message: str, code: str = "llm_error", status: int = 502):
        super().__init__(message)
        self.code, self.status = code, status


def client():
    global _client
    if _client is None:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set", "no_llm_key", 503)
        from google import genai
        _client = genai.Client(api_key=key)
    return _client


def model_candidates() -> list[str]:
    order = [_active_model, PRIMARY] + FALLBACKS
    seen, out = set(), []
    for m in order:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def list_gemma_models() -> list[str]:
    """Ask the API which Gemma 4 ids really exist (docs for these ids are in flux)."""
    try:
        names = [m.name.split("/")[-1] for m in client().models.list()]
        return sorted(n for n in names if n.startswith("gemma-4"))
    except Exception as exc:
        log.warning("Could not list models: %s", exc)
        return []


def active_model() -> str:
    return _active_model or PRIMARY


def _classify(exc: Exception) -> tuple[str, int]:
    s = str(exc).lower()
    if "429" in s or "quota" in s or "resource_exhausted" in s or "rate" in s:
        return "llm_busy", 429
    if "404" in s or "not found" in s or "not supported" in s:
        return "model_missing", 404
    return "llm_error", 502


def _generate(contents, stream: bool = False):
    """Try each candidate model until one works. Returns a response or stream iterator."""
    global _active_model
    last: Exception | None = None
    for model in model_candidates():
        try:
            c = client()
            if stream:
                it = c.models.generate_content_stream(model=model, contents=contents)
                first = next(iter(it), None)  # force the request so failures surface here
                _active_model = model
                return model, first, it
            resp = c.models.generate_content(model=model, contents=contents)
            _active_model = model
            return resp
        except LLMError:
            raise
        except Exception as exc:
            last = exc
            code, _ = _classify(exc)
            log.warning("Model %s failed (%s): %s", model, code, str(exc)[:200])
            if code != "model_missing":
                break
    code, status = _classify(last) if last else ("llm_error", 502)
    raise LLMError(str(last)[:300], code, status)


def _text(resp) -> str:
    try:
        return (resp.text or "").strip()
    except Exception:
        return ""


def _raw(chunk) -> str:
    """Chunk text WITHOUT stripping: whitespace between streamed tokens matters."""
    try:
        return chunk.text or ""
    except Exception:
        return ""


_MD_CHARS = re.compile(r"[*_`#>~|]+")


def _strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.strip()


# ---------- prompts ----------
def _style(lang: str) -> str:
    name = langs.LANGS.get(lang, langs.LANGS["en"])["name"]
    return (
        f"You are a friendly voice assistant. Reply ONLY in {name}, written in its native script. "
        "Your answer will be read aloud, so: 1 to 3 short spoken-style sentences, no markdown, "
        "no emojis, no bullet points, no URLs, and no English words except proper nouns."
    )


def translate(text: str, target: str, source: str | None = None) -> str:
    t = langs.LANGS.get(target)
    if not t:
        raise LLMError(f"Unsupported target '{target}'", "unsupported_lang", 400)
    src = f" from {langs.LANGS[source]['name']}" if source in langs.LANGS else ""
    prompt = (f"Translate the following text{src} into {t['name']} using its native script. "
              f"Output ONLY the translation, nothing else.\n\nText:\n{text}")
    return _strip_thinking(_text(_generate(prompt)))


def route_intent(text: str, lang: str) -> dict:
    """Return {"intent": time|weather|faq|chat, "city": str|None}."""
    from . import intents
    fast = intents.keyword_intent(text)
    if fast == "time":
        return {"intent": "time", "city": None}
    prompt = (
        "Classify the user's request. Reply with ONLY a JSON object like "
        '{"intent":"time|weather|faq|chat","city":null}. '
        "time = asks the current time or date. weather = asks about weather/rain/temperature "
        "(put the city name in Latin letters in \"city\", or null if none given). "
        "faq = asks about this assistant, this project, the hackathon or the models used. "
        "chat = anything else.\n\nUser request: " + text
    )
    try:
        raw = _strip_thinking(_text(_generate(prompt)))
        m = re.search(r"\{.*\}", raw, flags=re.S)
        data = json.loads(m.group(0)) if m else {}
        intent = data.get("intent") if data.get("intent") in {"time", "weather", "faq", "chat"} else "chat"
        city = data.get("city") if isinstance(data.get("city"), str) and data.get("city") else None
        return {"intent": intent, "city": city}
    except Exception as exc:
        log.warning("Intent routing fell back to keywords: %s", exc)
        return {"intent": fast or "chat", "city": None}


def _build_prompt(text: str, lang: str, history: list[dict], tool_result: str | None, has_image: bool) -> str:
    parts = [_style(lang)]
    if history:
        parts.append("Conversation so far:\n" + "\n".join(
            f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['text']}" for h in history))
    if tool_result:
        parts.append("Verified facts to base your answer on (state them naturally, do not invent more):\n" + tool_result)
    if has_image:
        parts.append("The user also attached a photo. Look at it and answer their question about it.")
    parts.append(f"User: {text}")
    return "\n\n".join(parts)


def _contents(prompt: str, image: bytes | None):
    if not image:
        return prompt
    from google.genai import types
    return [types.Part.from_bytes(data=image, mime_type="image/jpeg"), prompt]


def reply(text: str, lang: str, history: list[dict] | None = None,
          tool_result: str | None = None, image: bytes | None = None) -> str:
    prompt = _build_prompt(text, lang, history or [], tool_result, bool(image))
    out = _strip_thinking(_text(_generate(_contents(prompt, image))))
    if not out:
        raise LLMError("Empty reply from model", "empty_reply", 502)
    return clean_text(out)


def reply_stream(text: str, lang: str, history: list[dict] | None = None,
                 tool_result: str | None = None, image: bytes | None = None) -> Iterator[str]:
    """Yield text chunks as Gemma produces them."""
    prompt = _build_prompt(text, lang, history or [], tool_result, bool(image))
    _, first, it = _generate(_contents(prompt, image), stream=True)
    produced = False
    chunks = ([first] if first is not None else [])
    for chunk in chunks:
        t = _MD_CHARS.sub("", _raw(chunk))
        if t:
            produced = True
            yield t
    for chunk in it:
        t = _MD_CHARS.sub("", _raw(chunk))
        if t:
            produced = True
            yield t
    if not produced:
        raise LLMError("Empty reply from model", "empty_reply", 502)


def prepare_image(raw: bytes, max_side: int = 1024) -> bytes:
    """Shrink + re-encode as JPEG so uploads are small and always a format Gemma accepts."""
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()
