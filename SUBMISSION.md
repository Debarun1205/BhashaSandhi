# Submission text (fill the `<<…>>` parts)

## Pull request title
`Team J: Bolo, multilingual voice assistant (Whisper + Gemma 4 + MMS-TTS)`

## Pull request description

**Live URL:** <<https://…>>
**Repo (public, MIT):** <<https://github.com/…>>

### What we built
Bolo is a voice assistant for Hindi and Bengali speakers: speak, and it answers out loud in the same language. Odia is supported as typed input with spoken output. It can also answer questions about a photo, route simple intents (time, weather, FAQ), stream its reply, auto-detect the language, and fall back gracefully when offline.

### Tech used
- **Whisper large-v3** (open weights, MIT): speech to text + language ID (Groq-hosted; faster-whisper fallback)
- **Gemma 4** (`gemma-4-26b-a4b-it`) **through the Gemini API**: translation, intent routing, replies, image understanding, streaming
- **Meta MMS-TTS** (hi / bn / or): open-weight text to speech
- Flask + gunicorn, SQLite history, Server-Sent Events, service worker, Docker, DigitalOcean
- pytest suite + a real-model round-trip test (`tests/roundtrip.py`)

### Honest limits
Whisper has no Odia model, so Odia is typed-in and spoken-out. MMS voices are non-commercial licensed.

### Team
<<Name 1, Name 2, Name 3, Name 4>>

---

## OrganizerHQ form
- **Project name:** Bolo, Multilingual Voice Assistant
- **Challenges to select:** ✅ Best Open-Source AI Project  ✅ Best Use of Gemma 4
- **Description:** (paste "What we built" above)
- **Technologies:** Whisper large-v3, Gemma 4 (Gemini API), Meta MMS-TTS, Flask, SQLite, Docker, DigitalOcean
- **Repository:** <<public repo URL>>
- **Demo URL:** <<live URL>>

## Final checks before pressing submit
- [ ] LICENSE visible in the repo root, repo is public
- [ ] README top shows the live URL; models table links each license
- [ ] README names the exact Gemma 4 model id you really used (check `/health` → `llm_model`)
- [ ] `tests/roundtrip.py` passed against the live URL
- [ ] No API keys anywhere in the repo or its history
- [ ] Every team member is present (rule)
