"""REAL-model self-test, no human voice needed. Run against a live server (local or deployed):

    python tests/roundtrip.py https://your-app-url
    python tests/roundtrip.py                      # defaults to http://localhost:5000

Speaks a sentence with MMS-TTS (/api/speak) -> feeds the WAV to Whisper (/api/transcribe)
-> checks the language and that the transcript resembles the original. Then runs a full
/api/chat turn per language. Exits non-zero on any failure. Also a nice live proof for judges.
"""
import difflib
import re
import sys
import time

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000").rstrip("/")
CASES = [
    ("hi", "नमस्ते, आज मौसम बहुत अच्छा है।"),
    ("bn", "নমস্কার, আজ আবহাওয়া খুব সুন্দর।"),
]
rows, failed = [], False


def norm(s):
    return re.sub(r"[^\w]", "", s, flags=re.U).lower()


def record(name, ok, detail):
    global failed
    failed |= not ok
    rows.append((name, "PASS" if ok else "FAIL", detail))


h = requests.get(f"{BASE}/health", timeout=30).json()
record("health", h.get("status") == "ok", f"llm={h.get('llm_model')} stt={h.get('stt_backend')}")

for lang, sentence in CASES:
    try:
        t0 = time.time()
        sp = requests.post(f"{BASE}/api/speak", json={"text": sentence, "lang": lang}, timeout=180)
        ok = sp.status_code == 200 and sp.content[:4] == b"RIFF"
        record(f"speak[{lang}]", ok, f"{sp.headers.get('X-TTS-Backend')} {len(sp.content)//1024}KB {time.time()-t0:.1f}s")
        if not ok:
            continue
        tr = requests.post(f"{BASE}/api/transcribe", files={"audio": ("rt.wav", sp.content, "audio/wav")}, timeout=120).json()
        ratio = difflib.SequenceMatcher(None, norm(sentence), norm(tr.get("text", ""))).ratio()
        record(f"transcribe[{lang}]", tr.get("language") == lang and ratio >= 0.5,
               f"lang={tr.get('language')} similarity={ratio:.2f} text={tr.get('text')!r}")
    except Exception as exc:
        record(f"roundtrip[{lang}]", False, repr(exc))

for lang, q in [("hi", "अभी कितने बजे हैं?"), ("bn", "তুমি কে?"), ("or", "ଆପଣ କିଏ?")]:
    try:
        r = requests.post(f"{BASE}/api/chat", data={"text": q, "lang": lang, "session_id": "selftest"}, timeout=180)
        j = r.json()
        script = {"hi": (0x900, 0x97F), "bn": (0x980, 0x9FF), "or": (0xB00, 0xB7F)}[lang]
        in_script = sum(script[0] <= ord(c) <= script[1] for c in j.get("reply_text", ""))
        record(f"chat[{lang}]", r.status_code == 200 and in_script >= 3 and bool(j.get("audio_b64")),
               f"reply={j.get('reply_text', j.get('error'))!r:.70} audio={'yes' if j.get('audio_b64') else 'no'}")
    except Exception as exc:
        record(f"chat[{lang}]", False, repr(exc))

w = max(len(r[0]) for r in rows)
for name, status, detail in rows:
    print(f"{name:<{w}}  {status}  {detail}")
print("\nALL PASS" if not failed else "\nSOME CHECKS FAILED")
sys.exit(1 if failed else 0)
