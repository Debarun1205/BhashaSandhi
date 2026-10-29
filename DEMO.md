# 2-minute demo script

Warm-up (2 min before): open `/health`, speak one Hindi and one Bengali sentence.

1. **Hindi voice, 20 s.** Open the live URL on a phone. Tap the mic: "आज मौसम कैसा है?" → spoken Hindi weather for Haldia. Point at the stepper: *Transcribing → Thinking → Speaking*.
2. **Auto-detect, 20 s.** Leave Auto-detect on. Ask in Bengali: "এখন কয়টা বাজে?" → the language tag flips to বাংলা and the reply is spoken in Bengali.
3. **Multimodal (Gemma 4), 30 s.** Attach a photo (a plant, a snack, a sign). Ask in Hindi: "इस तस्वीर में क्या है?" → Gemma 4 describes it, spoken.
4. **Odia, 20 s.** Pick ଓଡ଼ିଆ, type "ଆପଣ କିଏ?" → spoken Odia. Say: "Whisper has no Odia model, so Odia is type-in, speak-out. MMS-TTS is the only open voice that covers it."
5. **Offline, 10 s.** Airplane mode → send a message → localized offline message.
6. **Proof, 20 s.** Open the README models table, then `/health`. Say: "Whisper, Gemma 4 through the Gemini API, and Meta MMS, all open-weight, MIT repo, deployed on DigitalOcean."

If something fails live, say what the fallback is (Replay button, browser voice, typed input). That reads as engineering, not luck.
