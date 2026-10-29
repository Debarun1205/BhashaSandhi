"""Language table, script detection and localized canned messages.

Every error path speaks the user's own language, never English to a Hindi speaker.
"""
from __future__ import annotations

# code -> metadata. `stt` = Whisper can transcribe it, `tts` = we can speak it.
LANGS = {
    "hi": {"name": "Hindi", "native": "हिन्दी", "mms": "hin", "gtts": "hi", "bcp47": "hi-IN",
           "range": (0x0900, 0x097F), "stt": True, "tts": True},
    "bn": {"name": "Bengali", "native": "বাংলা", "mms": "ben", "gtts": "bn", "bcp47": "bn-IN",
           "range": (0x0980, 0x09FF), "stt": True, "tts": True},
    # Whisper has no Odia model; Odia is typed-in, spoken-out via MMS-TTS.
    "or": {"name": "Odia", "native": "ଓଡ଼ିଆ", "mms": "ory", "gtts": None, "bcp47": "or-IN",
           "range": (0x0B00, 0x0B7F), "stt": False, "tts": True},
    "en": {"name": "English", "native": "English", "mms": None, "gtts": "en", "bcp47": "en-IN",
           "range": None, "stt": True, "tts": True},
}

# Whisper returns full English names with verbose_json; normalise to ISO codes.
WHISPER_NAMES = {
    "hindi": "hi", "bengali": "bn", "bangla": "bn", "english": "en", "odia": "or", "oriya": "or",
    "urdu": "ur", "marathi": "mr", "nepali": "ne", "assamese": "as",
}

MESSAGES = {
    "greeting": {
        "hi": "नमस्ते! मैं आपकी आवाज़ सहायक हूँ। बोलिए, मैं कैसे मदद करूँ?",
        "bn": "নমস্কার! আমি আপনার ভয়েস সহকারী। বলুন, কীভাবে সাহায্য করতে পারি?",
        "or": "ନମସ୍କାର! ମୁଁ ଆପଣଙ୍କ ସ୍ୱର ସହାୟକ। କୁହନ୍ତୁ, ମୁଁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି?",
        "en": "Hello! I am your voice assistant. How can I help?",
    },
    "retry": {
        "hi": "माफ़ कीजिए, मैं आपकी आवाज़ सुन नहीं पाया। कृपया फिर से बोलिए।",
        "bn": "দুঃখিত, আমি আপনার কথা শুনতে পাইনি। অনুগ্রহ করে আবার বলুন।",
        "or": "କ୍ଷମା କରିବେ, ମୁଁ ଆପଣଙ୍କ କଥା ଶୁଣିପାରିଲି ନାହିଁ। ଦୟାକରି ପୁଣି କୁହନ୍ତୁ।",
        "en": "Sorry, I could not hear you. Please try again.",
    },
    "busy": {
        "hi": "सेवा अभी व्यस्त है। कृपया कुछ देर बाद फिर कोशिश करें।",
        "bn": "পরিষেবা এখন ব্যস্ত। অনুগ্রহ করে কিছুক্ষণ পরে আবার চেষ্টা করুন।",
        "or": "ସେବା ବର୍ତ୍ତମାନ ବ୍ୟସ୍ତ ଅଛି। ଦୟାକରି କିଛି ସମୟ ପରେ ଚେଷ୍ଟା କରନ୍ତୁ।",
        "en": "The service is busy right now. Please try again in a moment.",
    },
    "offline": {
        "hi": "आप ऑफ़लाइन लगते हैं। कृपया इंटरनेट कनेक्शन जाँचें।",
        "bn": "আপনি অফলাইনে আছেন মনে হচ্ছে। অনুগ্রহ করে ইন্টারনেট সংযোগ দেখুন।",
        "or": "ଆପଣ ଅଫଲାଇନ୍ ଅଛନ୍ତି ବୋଲି ମନେ ହେଉଛି। ଇଣ୍ଟରନେଟ୍ ସଂଯୋଗ ଯାଞ୍ଚ କରନ୍ତୁ।",
        "en": "You appear to be offline. Please check your internet connection.",
    },
    "odia_type": {
        "hi": "ओड़िया की आवाज़ पहचान अभी उपलब्ध नहीं है। कृपया टाइप करें।",
        "bn": "ওড়িয়া ভয়েস শনাক্তকরণ এখনো নেই। অনুগ্রহ করে টাইপ করুন।",
        "or": "ଓଡ଼ିଆ ସ୍ୱର ଚିହ୍ନଟ ଏବେ ଉପଲବ୍ଧ ନାହିଁ। ଦୟାକରି ଟାଇପ୍ କରନ୍ତୁ।",
        "en": "Odia speech recognition is not available yet. Please type instead.",
    },
    "error": {
        "hi": "कुछ गड़बड़ हो गई। कृपया फिर से कोशिश करें।",
        "bn": "কিছু একটা সমস্যা হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।",
        "or": "କିଛି ଭୁଲ ହୋଇଗଲା। ଦୟାକରି ପୁଣି ଚେଷ୍ଟା କରନ୍ତୁ।",
        "en": "Something went wrong. Please try again.",
    },
}


def msg(key: str, lang: str) -> str:
    table = MESSAGES[key]
    return table.get(lang) or table["en"]


def normalize_code(value: str | None) -> str | None:
    """'Hindi' / 'hi' / 'hi-IN' -> 'hi'. Returns None when empty."""
    if not value:
        return None
    v = value.strip().lower()
    if v in WHISPER_NAMES:
        return WHISPER_NAMES[v]
    return v.split("-")[0].split("_")[0]


def is_supported(code: str | None) -> bool:
    return code in LANGS


def detect_script(text: str) -> str | None:
    """Return hi/bn/or if most letters of `text` are in that Unicode block, else None."""
    counts = {code: 0 for code, m in LANGS.items() if m["range"]}
    for ch in text:
        cp = ord(ch)
        for code, m in LANGS.items():
            r = m["range"]
            if r and r[0] <= cp <= r[1]:
                counts[code] += 1
                break
    best = max(counts, key=counts.get)
    return best if counts[best] >= 2 else None


def has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)
