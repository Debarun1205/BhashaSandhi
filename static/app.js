/* Bolo frontend: record -> /api/chat/stream (SSE) -> streamed text + spoken reply. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = { chat: $("chat"), hero: $("hero"), suggest: $("suggest"), mic: $("mic"), micnote: $("micnote"),
    text: $("text"), send: $("send"), stepper: $("stepper"), offline: $("offline"), langs: $("langs"),
    imageInput: $("imageInput"), preview: $("preview"), previewImg: $("previewImg"), removeImg: $("removeImg") };

  const BCP47 = { hi: "hi-IN", bn: "bn-IN", or: "or-IN", en: "en-IN" };
  const NAMES = { hi: "हिन्दी", bn: "বাংলা", or: "ଓଡ଼ିଆ", en: "English" };
  const OFFLINE = {
    hi: "आप ऑफ़लाइन लगते हैं। कृपया इंटरनेट कनेक्शन जाँचें।",
    bn: "আপনি অফলাইনে আছেন মনে হচ্ছে। অনুগ্রহ করে ইন্টারনেট সংযোগ দেখুন।",
    or: "ଆପଣ ଅଫଲାଇନ୍ ଅଛନ୍ତି ବୋଲି ମନେ ହେଉଛି। ଇଣ୍ଟରନେଟ୍ ସଂଯୋଗ ଯାଞ୍ଚ କରନ୍ତୁ।",
    en: "You appear to be offline. Please check your internet connection.",
  };
  const SUGGEST = {
    hi: ["आज मौसम कैसा है?", "अभी कितने बजे हैं?", "इस तस्वीर में क्या है?", "तुम कौन हो?"],
    bn: ["আজকের আবহাওয়া কেমন?", "এখন কয়টা বাজে?", "এই ছবিতে কী আছে?", "তুমি কে?"],
    or: ["ଆଜି ପାଣିପାଗ କିପରି?", "ବର୍ତ୍ତମାନ କେତେ ବାଜିଲା?", "ଆପଣ କିଏ?"],
    en: ["What's the weather in Kolkata?", "What time is it?", "What is in this photo?"],
  };

  const state = { lang: "auto", busy: false, recording: false, image: null, imageUrl: null, session: null,
    recorder: null, stream: null, chunks: [], audioCtx: null, raf: 0, stopTimer: 0, player: null };

  // ---------- session id (localStorage can throw in private mode) ----------
  try { state.session = localStorage.getItem("bolo-session"); } catch (_) {}
  if (!state.session) {
    state.session = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).replace(/-/g, "");
    try { localStorage.setItem("bolo-session", state.session); } catch (_) {}
  }

  // ---------- language chips + suggestions ----------
  function renderSuggestions() {
    const list = state.lang === "auto" ? [...SUGGEST.hi.slice(0, 2), ...SUGGEST.bn.slice(0, 2)] : SUGGEST[state.lang];
    el.suggest.innerHTML = "";
    list.forEach((s) => {
      const b = document.createElement("button");
      b.textContent = s;
      b.onclick = () => { el.text.value = s; submitText(); };
      el.suggest.append(b);
    });
  }
  el.langs.addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    state.lang = b.dataset.lang;
    el.langs.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b));
    el.text.placeholder = state.lang === "or" ? "ଏଠାରେ ଟାଇପ୍ କରନ୍ତୁ…" : "Or type here…";
    renderSuggestions();
  });
  renderSuggestions();

  // ---------- helpers ----------
  const scrollDown = () => { el.chat.scrollTop = el.chat.scrollHeight; };
  function addMsg(kind, html) {
    el.hero.hidden = true;
    const d = document.createElement("div");
    d.className = "msg " + kind;
    if (html) d.textContent = html;
    el.chat.append(d);
    scrollDown();
    return d;
  }
  function setLangAttr(node, lang) { if (lang && BCP47[lang]) node.lang = lang; }

  const STEPS = ["listening", "transcribing", "thinking", "speaking"];
  function setStep(step) {
    if (!step) { el.stepper.hidden = true; return; }
    el.stepper.hidden = false;
    const idx = STEPS.indexOf(step);
    el.stepper.querySelectorAll("span").forEach((s) => {
      const i = STEPS.indexOf(s.dataset.step);
      s.classList.toggle("active", i === idx);
      s.classList.toggle("done", i < idx);
    });
  }

  function setBusy(b) {
    state.busy = b;
    el.mic.disabled = b;
    el.send.disabled = b;
    el.micnote.textContent = b ? "Working…" : "Tap to talk";
  }

  // ---------- browser speech fallback (also used when offline / TTS fails) ----------
  function browserSpeak(text, lang) {
    try {
      if (!("speechSynthesis" in window)) return;
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = BCP47[lang] || "en-IN";
      speechSynthesis.speak(u);
    } catch (_) {}
  }

  function playAudio(b64, mime, bubble, lang, text) {
    if (!b64) { browserSpeak(text, lang); return; }
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: mime || "audio/wav" }));
    const play = () => {
      if (state.player) state.player.pause();
      state.player = new Audio(url);
      state.player.play().catch(() => {});
    };
    const meta = bubble.querySelector(".meta");
    const btn = document.createElement("button");
    btn.className = "replay";
    btn.textContent = "▶ Replay";
    btn.onclick = play;
    meta.prepend(btn);
    play();
  }

  // ---------- SSE over fetch (needed because we POST a file) ----------
  async function* sse(res) {
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, i);
        buf = buf.slice(i + 2);
        let name = "message", data = "";
        raw.split("\n").forEach((l) => {
          if (l.startsWith("event:")) name = l.slice(6).trim();
          else if (l.startsWith("data:")) data += l.slice(5).trim();
        });
        if (data) yield [name, JSON.parse(data)];
      }
    }
  }

  // ---------- one conversation turn ----------
  async function sendTurn({ audio, text }) {
    if (state.busy) return;
    setBusy(true);
    const imgFile = state.image, imgUrl = state.imageUrl;
    clearImage(false);

    const userBubble = addMsg("user");
    if (imgUrl) { const im = document.createElement("img"); im.src = imgUrl; im.alt = "Your photo"; userBubble.append(im); }
    const userText = document.createElement("div");
    if (text) userText.textContent = text; else userText.className = "dots";
    userBubble.append(userText);

    const bot = addMsg("bot");
    const botText = document.createElement("div");
    botText.className = "dots";
    const meta = document.createElement("div");
    meta.className = "meta";
    bot.append(botText, meta);
    const tag = (t) => { const s = document.createElement("span"); s.className = "tag"; s.textContent = t; meta.append(s); };

    const fd = new FormData();
    if (audio) fd.append("audio", audio, "rec." + (audio.type.includes("mp4") ? "m4a" : audio.type.includes("ogg") ? "ogg" : "webm"));
    if (text) fd.append("text", text);
    if (imgFile) fd.append("image", imgFile, imgFile.name || "photo.jpg");
    fd.append("lang", state.lang);
    fd.append("session_id", state.session);

    let lang = state.lang === "auto" ? "en" : state.lang;
    let replyText = "";
    let gotAudio = false;
    setStep(audio ? "transcribing" : "thinking");
    try {
      const res = await fetch("/api/chat/stream", { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw Object.assign(new Error(err.error || "HTTP " + res.status), { user: err.user_message });
      }
      for await (const [name, d] of sse(res)) {
        if (name === "status") setStep(d.step);
        else if (name === "transcript") {
          lang = d.language || lang;
          userText.className = "";
          userText.textContent = d.transcript;
          setLangAttr(userText, lang);
          tag(NAMES[lang] || lang);
        } else if (name === "intent") { if (d.intent !== "chat") tag(d.intent); }
        else if (name === "token") {
          botText.className = "";
          replyText += d.t;
          botText.textContent = replyText;
          setLangAttr(botText, lang);
          scrollDown();
        } else if (name === "reply") { replyText = d.reply_text; botText.textContent = replyText; }
        else if (name === "audio") { gotAudio = true; playAudio(d.audio_b64, d.audio_mime, bot, lang, replyText); if (d.tts_backend) tag(d.tts_backend.replace("facebook/", "")); }
        else if (name === "error") throw Object.assign(new Error(d.error), { user: d.user_message });
        else if (name === "done") {
          const t = d.timings || {};
          const total = (t.stt_ms || 0) + (t.llm_ms || 0) + (t.tts_ms || 0);
          if (total > 0) tag((total / 1000).toFixed(1) + "s");
        }
      }
      if (!gotAudio && replyText) browserSpeak(replyText, lang);
    } catch (err) {
      bot.classList.add("err");
      const offline = !navigator.onLine || err instanceof TypeError;
      const shown = offline ? OFFLINE[lang] || OFFLINE.en : err.user || err.message;
      botText.className = "";
      botText.textContent = shown;
      setLangAttr(botText, lang);
      if (userText.className === "dots") { userText.className = ""; userText.textContent = "🎤"; }
      browserSpeak(shown, lang);
    } finally {
      setStep(null);
      setBusy(false);
      scrollDown();
    }
  }

  function submitText() {
    const t = el.text.value.trim();
    if (!t && !state.image) return;
    el.text.value = "";
    const photoQ = { bn: "এই ছবিতে কী আছে?", or: "ଏହି ଫଟୋରେ କ'ଣ ଅଛି?", en: "What is in this photo?" };
    sendTurn({ text: t || photoQ[state.lang] || "इस तस्वीर में क्या है?" });
  }
  el.send.onclick = submitText;
  el.text.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submitText(); } });

  // ---------- image attach ----------
  function clearImage(revoke = true) {
    if (revoke && state.imageUrl) URL.revokeObjectURL(state.imageUrl);
    state.image = null; state.imageUrl = null;
    el.preview.hidden = true; el.imageInput.value = "";
  }
  el.imageInput.addEventListener("change", () => {
    const f = el.imageInput.files[0];
    if (!f) return;
    state.image = f;
    state.imageUrl = URL.createObjectURL(f);
    el.previewImg.src = state.imageUrl;
    el.preview.hidden = false;
  });
  el.removeImg.onclick = () => clearImage();

  // ---------- recording ----------
  function pickMime() {
    const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
    return cands.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || "";
  }

  async function startRecording() {
    if (state.busy || state.recording) return;
    if (state.lang === "or") { addMsg("bot err", "ଓଡ଼ିଆ ସ୍ୱର ଚିହ୍ନଟ ଏବେ ଉପଲବ୍ଧ ନାହିଁ। ଦୟାକରି ଟାଇପ୍ କରନ୍ତୁ। (Odia speech recognition is not available. Please type.)"); return; }
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      addMsg("bot err", "Microphone blocked. Allow mic access (this page must be on https) or type instead.");
      return;
    }
    const mime = pickMime();
    state.chunks = [];
    state.recorder = new MediaRecorder(state.stream, mime ? { mimeType: mime } : undefined);
    state.recorder.ondataavailable = (e) => { if (e.data.size) state.chunks.push(e.data); };
    state.recorder.onstop = () => {
      const blob = new Blob(state.chunks, { type: state.recorder.mimeType || mime || "audio/webm" });
      cleanupRecording();
      sendTurn({ audio: blob });
    };
    state.recorder.start();
    state.recording = true;
    el.mic.classList.add("rec");
    el.mic.setAttribute("aria-label", "Stop recording");
    el.micnote.textContent = "Listening… tap to stop";
    setStep("listening");
    meter(state.stream);
    state.stopTimer = setTimeout(stopRecording, 30000); // hard cap: 30 s
  }

  function stopRecording() {
    if (!state.recording) return;
    state.recording = false;
    clearTimeout(state.stopTimer);
    el.mic.classList.remove("rec");
    el.mic.setAttribute("aria-label", "Start recording");
    try { state.recorder.stop(); } catch (_) {}
  }

  function cleanupRecording() {
    cancelAnimationFrame(state.raf);
    el.mic.style.removeProperty("--lvl");
    if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
    if (state.audioCtx) { state.audioCtx.close().catch(() => {}); state.audioCtx = null; }
  }

  function meter(stream) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      state.audioCtx = new Ctx();
      const an = state.audioCtx.createAnalyser();
      an.fftSize = 256;
      state.audioCtx.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.frequencyBinCount);
      const tick = () => {
        an.getByteTimeDomainData(buf);
        let peak = 0;
        for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
        el.mic.style.setProperty("--lvl", Math.min(1, peak / 64).toFixed(2));
        state.raf = requestAnimationFrame(tick);
      };
      tick();
    } catch (_) {}
  }

  el.mic.onclick = () => (state.recording ? stopRecording() : startRecording());

  // ---------- offline handling + service worker ----------
  function updateOnline() {
    const off = !navigator.onLine;
    el.offline.hidden = !off;
    if (off) el.offline.textContent = OFFLINE.hi + "  ·  " + OFFLINE.bn;
  }
  window.addEventListener("online", updateOnline);
  window.addEventListener("offline", updateOnline);
  updateOnline();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
