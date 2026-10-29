"""Run the UI with NO API keys and NO model downloads (stand-in STT / Gemma / TTS).
    python tests/dev_mock_server.py        ->  http://localhost:5055
Good for working on the frontend and for rehearsing without internet. NOT the real pipeline.
"""
import io, os, sys, time
import numpy as np
from scipy.io import wavfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", "/tmp/team_j_mock.db")
import app as appmod
from services import langs, llm, stt, tts


def tone(text, lang):
    rate = 16000
    t = np.linspace(0, 0.8, int(rate * 0.8), endpoint=False)
    buf = io.BytesIO()
    wavfile.write(buf, rate, (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16))
    return buf.getvalue(), "audio/wav", "mock-tone"

REPLIES = {"hi": "आज मौसम साफ़ है और तापमान अठाईस डिग्री है।", "bn": "আজ আবহাওয়া পরিষ্কার, তাপমাত্রা আঠাশ ডিগ্রি।",
           "or": "ଆଜି ପାଣିପାଗ ସ୍ୱଚ୍ଛ ଅଛି।", "en": "It is clear and 28 degrees today."}

def mock_stt(audio, filename="a.webm", language=None):
    if language == "or":
        raise stt.STTError("Whisper does not support Odia speech.", "odia_voice_unsupported", 400)
    time.sleep(0.3)
    return {"text": "आज मौसम कैसा है?", "language": "hi", "backend": "mock", "duration_ms": 300}

def mock_stream(text, lang, history=None, tool_result=None, image=None):
    prefix = "(photo received) " if image else ""
    for w in (prefix + REPLIES.get(lang, REPLIES["en"])).split(" "):
        time.sleep(0.08)
        yield w + " "

stt.transcribe = mock_stt
tts.synthesize = tone
llm.route_intent = lambda text, lang: {"intent": "chat", "city": None}
llm.reply_stream = mock_stream
llm.reply = lambda text, lang, history=None, tool_result=None, image=None: REPLIES.get(lang, REPLIES["en"])
llm.translate = lambda text, target, source=None: f"[{target}] {text}"

if __name__ == "__main__":
    appmod.RATE_PER_MIN = 0
    appmod.app.run(host="0.0.0.0", port=5055)
