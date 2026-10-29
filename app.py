"""Team J: Multilingual Voice Assistant (Flask).

Pipeline:  mic -> Whisper (STT) -> Gemma 4 via Gemini API (route intent, tools, reply, vision)
           -> Meta MMS-TTS (speech) -> browser
"""
import base64
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict

from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from services import intents, langs, llm, store, stt, tts

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "12")) * 1024 * 1024
CORS(app)

PROJECT = "Team J: Multilingual Voice Assistant"
_gemma_available: list[str] = []


# ---------------------------------------------------------------- errors
class AppError(Exception):
    def __init__(self, message, code="bad_request", status=400, lang="en"):
        super().__init__(message)
        self.message, self.code, self.status, self.lang = message, code, status, lang


def error_payload(exc: Exception, lang: str = "en") -> tuple[dict, int]:
    """Map any pipeline exception to a JSON body with a localized `user_message`."""
    code = getattr(exc, "code", "error")
    status = getattr(exc, "status", 500)
    key = {"no_speech": "retry", "stt_busy": "busy", "llm_busy": "busy",
           "odia_voice_unsupported": "odia_type"}.get(code, "error")
    return {"error": str(exc), "code": code, "user_message": langs.msg(key, lang)}, status


@app.errorhandler(AppError)
def _app_error(exc):
    body, status = error_payload(exc, exc.lang)
    return jsonify(body), status


@app.errorhandler(413)
def _too_large(_):
    return jsonify(error="Upload too large", code="too_large", user_message=langs.msg("error", "en")), 413


@app.errorhandler(404)
def _not_found(_):
    return jsonify(error="Not found", code="not_found"), 404


@app.errorhandler(Exception)
def _unhandled(exc):
    if hasattr(exc, "code") and isinstance(getattr(exc, "code"), int):  # werkzeug HTTPException
        return jsonify(error=getattr(exc, "description", str(exc)), code="http_error"), exc.code
    if isinstance(exc, (stt.STTError, llm.LLMError, tts.TTSError)):
        body, status = error_payload(exc)
        return jsonify(body), status
    log.exception("Unhandled error")
    return jsonify(error="Internal error", code="internal", user_message=langs.msg("error", "en")), 500


# ---------------------------------------------------------------- rate limit
_buckets: dict = defaultdict(lambda: [0.0, 0.0])  # ip -> [tokens, last_ts]
RATE_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "40"))


@app.before_request
def _rate_limit():
    if not request.path.startswith("/api/") or RATE_PER_MIN <= 0:
        return None
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "?")).split(",")[0].strip()
    now = time.time()
    tokens, last = _buckets[ip]
    tokens = RATE_PER_MIN if last == 0 else min(RATE_PER_MIN, tokens + (now - last) * RATE_PER_MIN / 60)
    if tokens < 1:
        _buckets[ip] = [tokens, now]
        return jsonify(error="Too many requests", code="rate_limited",
                       user_message=langs.msg("busy", "en")), 429
    _buckets[ip] = [tokens - 1, now]
    return None


# ---------------------------------------------------------------- upload helpers
def sniff_audio(data: bytes) -> str | None:
    """Validate by magic bytes (not the client-supplied MIME) and return a file extension."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or (len(data) > 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    if data[:4] == b"fLaC":
        return "flac"
    return None


def read_audio(file_storage) -> tuple[bytes, str]:
    data = file_storage.read()
    if len(data) < 800:
        raise AppError("Audio clip is empty or too short", "no_speech", 422)
    ext = sniff_audio(data)
    if not ext:
        raise AppError("Unsupported audio format (use webm, ogg, wav, mp3, m4a or flac)", "bad_audio", 415)
    return data, ext


# ---------------------------------------------------------------- pages
@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/health")
def health():
    return jsonify(
        status="ok", project=PROJECT, stack="flask",
        stt_backend=stt.backend_name(), stt_model=stt.GROQ_MODEL if stt.backend_name() == "groq" else "faster-whisper",
        llm_model=llm.active_model(), gemma_models_available=_gemma_available,
        tts_backends=["facebook/mms-tts-hin", "facebook/mms-tts-ben", "facebook/mms-tts-ory", "gtts-fallback"],
        models_loaded={"tts": tts.loaded()},
        keys_present={"gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
                      "groq": bool(os.getenv("GROQ_API_KEY"))},
    )


@app.get("/api/languages")
def languages():
    return jsonify([{"code": c, "name": m["name"], "native": m["native"], "stt": m["stt"], "tts": m["tts"],
                     "bcp47": m["bcp47"]} for c, m in langs.LANGS.items()])


# ---------------------------------------------------------------- building-block endpoints
@app.post("/api/transcribe")
def api_transcribe():
    f = request.files.get("audio")
    if not f:
        raise AppError("Send the recording as multipart field 'audio'", "missing_audio", 400)
    data, ext = read_audio(f)
    result = stt.transcribe(data, f"audio.{ext}", request.form.get("language"))
    return jsonify(text=result["text"], language=result["language"],
                   backend=result["backend"], duration_ms=result["duration_ms"])


@app.post("/api/translate")
def api_translate():
    body = request.get_json(silent=True) or {}
    text, target = (body.get("text") or "").strip(), langs.normalize_code(body.get("target"))
    if not text or target not in langs.LANGS:
        raise AppError("Body must be {text, target} with target in hi/bn/or/en", "bad_request", 400)
    if len(text) > 2000:
        raise AppError("Text too long (max 2000 characters)", "too_long", 413)
    source = langs.normalize_code(body.get("source")) or langs.detect_script(text) or "en"
    return jsonify(text=llm.translate(text, target, source), source=source, target=target)


@app.post("/api/speak")
def api_speak():
    body = request.get_json(silent=True) or {}
    text, lang = (body.get("text") or "").strip(), langs.normalize_code(body.get("lang"))
    if not text or lang not in langs.LANGS:
        raise AppError("Body must be {text, lang} with lang in hi/bn/or/en", "bad_request", 400)
    audio, mime, backend = tts.synthesize(text, lang)
    resp = Response(audio, mimetype=mime)
    resp.headers["X-TTS-Backend"] = backend
    resp.headers["Access-Control-Expose-Headers"] = "X-TTS-Backend"
    return resp


# ---------------------------------------------------------------- the product: /api/chat
def parse_chat_request() -> dict:
    """Read and validate everything from the request up front (bytes, not file handles)."""
    form = request.form
    pinned = form.get("lang", "").strip().lower()
    pinned = None if pinned in ("", "auto") else langs.normalize_code(pinned)
    if pinned and pinned not in langs.LANGS:
        raise AppError("Unsupported language", "unsupported_lang", 400)
    req = {"session_id": (form.get("session_id") or uuid.uuid4().hex)[:64], "pinned": pinned,
           "text": (form.get("text") or "").strip()[:1000], "audio": None, "ext": None, "image": None}
    if "audio" in request.files and request.files["audio"].filename is not None:
        if pinned == "or":
            raise AppError("Odia speech recognition is not available", "odia_voice_unsupported", 400, "or")
        req["audio"], req["ext"] = read_audio(request.files["audio"])
    if "image" in request.files:
        try:
            req["image"] = llm.prepare_image(request.files["image"].read())
        except Exception as exc:
            raise AppError(f"Could not read image: {exc}", "bad_image", 415) from exc
    if not req["audio"] and not req["text"]:
        raise AppError("Send 'audio' or 'text'", "missing_input", 400)
    return req


def pick_language(pinned, transcript, whisper_lang):
    """Pinned choice wins; then the script of the text; then Whisper's guess; else English."""
    if pinned in langs.LANGS:
        return pinned
    return langs.detect_script(transcript) or (whisper_lang if whisper_lang in langs.LANGS else "en")


def event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def chat_events(req: dict, stream: bool):
    """Generator of (event_name, payload). Both chat endpoints use this single pipeline."""
    timings, lang = {}, req["pinned"] or "en"
    try:
        transcript, whisper_lang = req["text"], None
        if req["audio"]:
            yield "status", {"step": "transcribing"}
            res = stt.transcribe(req["audio"], f"audio.{req['ext']}", req["pinned"])
            transcript, whisper_lang = res["text"], res["language"]
            timings["stt_ms"] = res["duration_ms"]
        lang = pick_language(req["pinned"], transcript, whisper_lang)
        yield "transcript", {"transcript": transcript, "language": lang, "session_id": req["session_id"]}

        yield "status", {"step": "thinking"}
        t0 = time.time()
        hist = store.history(req["session_id"])
        if req["image"]:
            route = {"intent": "chat", "city": None}
        else:
            route = llm.route_intent(transcript, lang)
        tool = intents.run_tool(route["intent"], transcript, route["city"])
        yield "intent", {"intent": route["intent"]}

        pieces = []
        if stream:
            for chunk in llm.reply_stream(transcript, lang, hist, tool, req["image"]):
                pieces.append(chunk)
                yield "token", {"t": chunk}
            reply_text = tts.clean_text("".join(pieces))
        else:
            reply_text = llm.reply(transcript, lang, hist, tool, req["image"])
            yield "token", {"t": reply_text}
        timings["llm_ms"] = int((time.time() - t0) * 1000)
        store.add_turn(req["session_id"], "user", transcript, lang, route["intent"])
        store.add_turn(req["session_id"], "assistant", reply_text, lang, route["intent"])
        yield "reply", {"reply_text": reply_text}

        yield "status", {"step": "speaking"}
        t0 = time.time()
        try:
            audio, mime, backend = tts.synthesize(reply_text, lang)
            yield "audio", {"audio_b64": base64.b64encode(audio).decode(), "audio_mime": mime, "tts_backend": backend}
        except tts.TTSError as exc:  # text reply still succeeds; browser will use speechSynthesis
            log.warning("TTS failed: %s", exc)
            yield "audio", {"audio_b64": None, "audio_mime": None, "tts_backend": None, "tts_error": str(exc)}
        timings["tts_ms"] = int((time.time() - t0) * 1000)
        yield "done", {"timings": timings, "language": lang}
    except (stt.STTError, llm.LLMError, tts.TTSError, AppError) as exc:
        body, status = error_payload(exc, lang)
        body["status"] = status
        yield "error", body
    except Exception as exc:
        log.exception("chat pipeline crashed")
        body, status = error_payload(exc, lang)
        body["status"] = 500
        yield "error", body


@app.post("/api/chat")
def api_chat():
    req = parse_chat_request()
    out = {"session_id": req["session_id"], "audio_b64": None, "audio_mime": None}
    for name, data in chat_events(req, stream=False):
        if name == "error":
            return jsonify({k: v for k, v in data.items() if k != "status"}), data["status"]
        if name in ("transcript", "intent", "reply", "audio"):
            out.update(data)
        elif name == "done":
            out.update(data)
    return jsonify(out)


@app.post("/api/chat/stream")
def api_chat_stream():
    req = parse_chat_request()

    @stream_with_context
    def gen():
        for name, data in chat_events(req, stream=True):
            yield event(name, data)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/history")
def api_history():
    sid = request.args.get("session_id", "")
    if not sid:
        raise AppError("session_id is required", "bad_request", 400)
    return jsonify(store.history(sid, int(request.args.get("limit", 20))))


# ---------------------------------------------------------------- startup
def _background_startup():
    global _gemma_available
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        _gemma_available = llm.list_gemma_models()
        log.info("Gemma 4 models available on the Gemini API: %s", _gemma_available)
    pre = [c.strip() for c in os.getenv("TTS_PRELOAD", "").split(",") if c.strip() in langs.LANGS]
    if pre:
        tts.preload(pre)


threading.Thread(target=_background_startup, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.getenv("FLASK_DEBUG") == "1")
