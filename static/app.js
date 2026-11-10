/* OEL — Offline English Learning · front end (vanilla, no build step) */
"use strict";

/* ─────────────────────────── helpers ─────────────────────────── */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function setStatus(text) { $("statusText").textContent = text; }

async function postJSON(url, data) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data ?? {}),
  });
  let body = null;
  try { body = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok) {
    const detail = body && (body.detail || body.error);
    const err = new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
    err.status = res.status; err.body = body;
    throw err;
  }
  return body;
}

async function postBlob(url, data) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data ?? {}),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const j = await res.json(); msg = j.error || j.detail || msg; } catch (_) {}
    const err = new Error(msg); err.status = res.status; throw err;
  }
  return res.blob();
}

/* ─────────────────────────── state ─────────────────────────── */
const state = {
  settings: {
    ttsEngine: "auto", asrMode: "auto", rate: 1, pitch: 1,
    maxSentences: 2, maxWords: 30, wholeText: false,
  },
  health: null,
  chunks: [], current: 0, filename: "", sourceText: "",
  micId: localStorage.getItem("xl_mic") || "",
  playing: false, stopFlag: false, currentAudio: null, watchdog: null,
  textEl: null, ranges: [],
  recording: false, mr: null, stream: null, recParts: [], mimeType: "",
  timerIv: null, recStart: 0, meter: null,
  lastTranscript: "", lastEngine: "", lastFeedback: null,
  lastRecordingUrl: null,
  study: { title: "", questions: [], index: 0, answers: {}, revealed: {}, meta: null },
  log: JSON.parse(localStorage.getItem("xl_log") || "[]"),
};

/* ─────────────────────────── views ─────────────────────────── */
const SAMPLE_TEXT = `Good morning, everyone. My name is Bangkit, and I study English Education at UNESA.

Subject verb agreement is one of the hardest parts of grammar for Indonesian learners. The number of students who make this mistake is larger than you think. A number of my classmates still mix them up.

I am interested in finding the rule before I memorize the pattern. When the subject is singular, the verb takes an s. When the subject is plural, the verb keeps its base form. The rule is simple, but we need to practise it every day.`;

function switchView(name) {
  if (state.playing) stopPlayback();
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === `view-${name}`));
  const titles = {
    listen: "Speaking & Listening · Listen",
    practice: "Speaking & Listening · Practice",
    study: "Learn 101 · Study",
    settings: "Settings",
  };
  $("subbar").hidden = name === "home";
  $("subTitle").textContent = titles[name] || "";
  if (name === "settings") { renderHealthBox(); refreshMics(); }
  if (name === "study") renderStudyQuestion();
}

/* ─────────────────────────── health ─────────────────────────── */
async function loadHealth() {
  try {
    const h = await fetch("/api/health").then((r) => r.json());
    state.health = h;
    const t = h.tts || {}, a = h.asr || {};
    const ttsBits = [
      t.piper_voice ? "piper✓" : (t.piper ? "piper↓" : null),
      t.gtts ? "gtts✓" : null, t.ffmpeg ? "ffmpeg✓" : null,
    ].filter(Boolean).join(" ");
    $("chipTts").textContent = `tts ${ttsBits || "?"}`;
    $("chipTts").className = `chip ${t.ffmpeg || t.gtts ? "good" : "warn"}`;

    let asrTxt = "asr offline", asrCls = "warn";
    if (a.installed && a.ready) { asrTxt = `asr ${a.model} ✓`; asrCls = "good"; }
    else if (a.installed && a.loading) { asrTxt = `asr ${a.model} memuat…`; asrCls = "warn"; }
    else if (a.installed && a.error) { asrTxt = "asr error"; asrCls = "bad"; }
    $("chipAsr").textContent = asrTxt;
    $("chipAsr").className = `chip ${asrCls}`;
    updateHintTexts();
  } catch (e) {
    $("chipAsr").textContent = "server mati";
    $("chipAsr").className = "chip bad";
  }
}

function updateHintTexts() {
  const h = state.health;
  if (!h) return;
  const t = h.tts || {}, a = h.asr || {};
  const engine = state.settings.ttsEngine;
  $("ttsHint").textContent =
    `piper voice: ${t.piper_voice ? "siap" : (t.piper ? "belum diunduh (auto saat start)" : "tidak terpasang")} · gtts: ${t.gtts ? "siap" : "-"} · ffmpeg: ${t.ffmpeg ? "ya" : "tidak"} · engine dipakai: ${engine}`;
  $("asrHint").textContent =
    a.installed
      ? `faster-whisper terpasang, model ${a.model}: ${a.ready ? "siap" : (a.loading ? "masih memuat model…" : (a.error || "belum dimuat"))}. ffmpeg: ${a.ffmpeg ? "ya" : "tidak"}.`
      : "faster-whisper belum terpasang — jalankan: pip install faster-whisper";
}

/* ─────────────────────────── settings ─────────────────────────── */
async function loadSettings() {
  try {
    const s = await fetch("/api/settings").then((r) => r.json());
    Object.assign(state.settings, {
      ttsEngine: s.ttsEngine, asrMode: s.asrMode, rate: Number(s.rate) || 1,
      pitch: Number(s.pitch) || 1,
      maxSentences: s.maxSentences, maxWords: s.maxWords,
      wholeText: Boolean(s.wholeText),
    });
    $("setTts").value = s.ttsEngine;
    $("engineSelect").value = s.ttsEngine;
    $("setAsr").value = s.asrMode;
    $("setRate").value = state.settings.rate;
    $("rateRange").value = state.settings.rate;
    $("setRateVal").textContent = state.settings.rate.toFixed(2) + "×";
    $("rateVal").textContent = state.settings.rate.toFixed(2) + "×";
    $("setPitch").value = state.settings.pitch;
    $("pitchRange").value = state.settings.pitch;
    $("setPitchVal").textContent = state.settings.pitch.toFixed(2) + "×";
    $("pitchVal").textContent = state.settings.pitch.toFixed(2) + "×";
    $("setSent").value = s.maxSentences;
    $("setWords").value = s.maxWords;
    $("wholeToggle").checked = Boolean(s.wholeText);
    $("parsePasteBtn").textContent = s.wholeText ? "Muat teks utuh" : "Potong jadi chunk";
  } catch (_) { /* server not up yet */ }
}

async function saveSettings(patch, quiet) {
  try {
    const s = await postJSON("/api/settings", patch);
    if (patch.ttsEngine !== undefined) state.settings.ttsEngine = s.ttsEngine;
    if (patch.asrMode !== undefined) state.settings.asrMode = s.asrMode;
    if (patch.rate !== undefined) state.settings.rate = Number(s.rate);
    if (patch.pitch !== undefined) state.settings.pitch = Number(s.pitch);
    if (patch.maxSentences !== undefined) state.settings.maxSentences = s.maxSentences;
    if (patch.maxWords !== undefined) state.settings.maxWords = s.maxWords;
    if (patch.wholeText !== undefined) state.settings.wholeText = Boolean(s.wholeText);
    if (!quiet) setStatus("settings tersimpan");
    updateHintTexts();
    return s;
  } catch (e) {
    $("settingsErr").textContent = e.message;
    return null;
  }
}

/* ─────────────────────────── listen: text in ─────────────────────────── */
function applyResult(data) {
  if (state.playing) stopPlayback();
  state.chunks = data.chunks;
  state.sourceText = data.text;
  state.filename = data.filename;
  state.current = 0;
  $("listenErr").textContent = "";
  $("chunkMeta").textContent = `${data.stats.chunks} chunk · ${data.stats.sentences} kalimat · ${data.stats.words} kata`;
  $("chunkEmpty").style.display = state.chunks.length ? "none" : "";
  renderChunkList();
  renderStage();
  setStatus(`${data.filename}: ${state.chunks.length} chunk siap`);
}

async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file, file.name);
  const qs = `?max_sentences=${state.settings.maxSentences}&max_words=${state.settings.maxWords}` +
    `&whole=${state.settings.wholeText ? 1 : 0}`;
  setStatus("membaca file…");
  try {
    const res = await fetch("/api/upload" + qs, { method: "POST", body: fd });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || `HTTP ${res.status}`);
    }
    applyResult(await res.json());
  } catch (e) {
    $("listenErr").textContent = e.message;
    setStatus("gagal membaca file");
  }
}

async function parsePasted() {
  const text = $("pasteBox").value.trim();
  if (!text) { $("listenErr").textContent = "Belum ada teks di kotak tempel."; return; }
  setStatus("memotong teks…");
  try {
    applyResult(await postJSON("/api/parse", {
      text, filename: "pasted.txt",
      maxSentences: state.settings.maxSentences, maxWords: state.settings.maxWords,
      whole: state.settings.wholeText,
    }));
  } catch (e) { $("listenErr").textContent = e.message; }
}

function renderChunkList() {
  const list = $("chunkList");
  list.innerHTML = state.chunks.map((c, i) => `
    <li data-i="${i}" class="${i === state.current ? "active" : ""}">
      <span class="n">${String(i + 1).padStart(2, "0")}</span>
      <span class="t">${esc(c.text)}</span>
      <span class="w">${c.words}w</span>
    </li>`).join("");
  list.querySelectorAll("li").forEach((li) => li.addEventListener("click", () => {
    selectChunk(Number(li.dataset.i));
  }));
}

function currentChunk() { return state.chunks[state.current] || null; }

function selectChunk(i) {
  if (!state.chunks.length) return;
  if (state.playing) stopPlayback();
  state.current = Math.max(0, Math.min(i, state.chunks.length - 1));
  renderChunkList();
  renderStage();
  const active = $("chunkList").querySelector("li.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

function wordRanges(text) {
  const out = []; const re = /\S+/g; let m;
  while ((m = re.exec(text))) out.push({ start: m.index, end: m.index + m[0].length });
  return out;
}

function renderWordsInto(el, text) {
  const ranges = wordRanges(text);
  el.innerHTML = ranges.map((r, i) =>
    `<span class="w" data-i="${i}" data-start="${r.start}">${esc(text.slice(r.start, r.end))}</span>`
  ).join(" ");
  el._ranges = ranges; el._hi = -1;
  return ranges;
}

function highlightAt(charPos) {
  const el = state.textEl;
  if (!el || !el._ranges) return;
  let idx = -1;
  const ranges = el._ranges;
  for (let i = 0; i < ranges.length; i++) { if (ranges[i].start <= charPos) idx = i; else break; }
  if (idx === el._hi) return;
  const prev = el.querySelector(".w.on");
  if (prev) prev.classList.remove("on");
  const cur = el.querySelector(`[data-i="${idx}"]`);
  if (cur) cur.classList.add("on");
  el._hi = idx;
}

function clearHighlight() {
  const el = state.textEl;
  if (!el) return;
  const prev = el.querySelector(".w.on");
  if (prev) prev.classList.remove("on");
  el._hi = -1;
}

function renderStage() {
  const c = currentChunk();
  const stage = $("stageText");
  if (!c) {
    state.textEl = null;
    stage.textContent = "Pilih chunk di kiri.";
    $("stageIndex").textContent = "—";
    $("exportBox").textContent = "—";
    return;
  }
  $("stageIndex").textContent = `chunk ${String(state.current + 1).padStart(2, "0")} / ${String(state.chunks.length).padStart(2, "0")}`;
  state.textEl = stage;
  renderWordsInto(stage, c.text);
  $("exportBox").textContent = state.chunks.map((x) => x.text).join("\n\n");
  $("listenHint").textContent =
    `Engine: ${resolveEngineLabel()} · rate ${state.settings.rate.toFixed(2)}× · ` +
    `pitch ${state.settings.pitch.toFixed(2)}× · ` +
    `${c.sentences.length} kalimat, ${c.words} kata.`;
  if ($("view-practice").classList.contains("active")) renderPracticeStage();
}

function renderPracticeStage() {
  const c = currentChunk();
  $("pIndex").textContent = c ? `chunk ${String(state.current + 1).padStart(2, "0")}` : "—";
  $("pMeta").textContent = c ? `${c.words} kata · ${c.sentences.length} kalimat` : "";
  $("pReference").textContent = c ? c.text : "Belum ada chunk.";
  state.textEl = null;
}

/* ─────────────────────────── listen: playback ─────────────────────────── */
function resolveEngine() {
  const pref = state.settings.ttsEngine;
  if (pref === "piper" || pref === "gtts") return pref;
  return "auto";
}

function resolveEngineLabel() {
  const e = resolveEngine();
  if (e === "piper") return "piper (offline)";
  if (e === "gtts") return "gtts (online)";
  return "server (piper → gtts)";
}

function setTransport(playing) {
  state.playing = playing;
  $("playBtn").disabled = playing;
  $("stopBtn").disabled = !playing;
  $("playBtn").textContent = playing ? "▶ …" : "▶ Dengarkan";
}

function stopPlayback() {
  state.stopFlag = true;
  if (state.currentAudio) {
    try { state.currentAudio.pause(); state.currentAudio.currentTime = 0; } catch (_) {}
    state.currentAudio = null;
  }
  clearHighlight();
}

function playBlob(blob, ranges, absOffset, sentenceLen) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    state.currentAudio = audio;
    let raf = 0;
    const cleanup = () => {
      cancelAnimationFrame(raf);
      URL.revokeObjectURL(url);
      state.currentAudio = null;
    };
    audio.onended = () => { cleanup(); resolve(); };
    audio.onerror = () => { cleanup(); reject(new Error("audio tidak bisa diputar")); };
    audio.play().catch((e) => { cleanup(); reject(e); });
    const tick = () => {
      if (state.stopFlag) { audio.pause(); cleanup(); resolve(); return; }
      const dur = audio.duration || 0;
      if (dur > 0 && ranges && ranges.length) {
        highlightAt(absOffset + Math.floor(audio.currentTime / dur * sentenceLen));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  });
}

async function speakServer(chunk, engine) {
  // Capture the current stage once: switching views mid-playback nulls state.textEl.
  const el = state.textEl;
  const ranges = (el && el._ranges) ? el._ranges : [];
  // One request for the whole chunk: no per-sentence gaps at every full stop.
  const blob = await postBlob("/api/tts", {
    text: chunk.text,
    engine: engine === "auto" ? "auto" : engine,
    rate: state.settings.rate,
    pitch: state.settings.pitch,
  });
  if (state.stopFlag) return;
  await playBlob(blob, ranges, 0, chunk.text.length);
}

async function playChunk() {
  const c = currentChunk();
  if (!c) { setStatus("belum ada chunk"); return; }
  stopPlayback();
  state.stopFlag = false;
  setTransport(true);
  setStatus(`memutar dengan ${resolveEngineLabel()}…`);
  try {
    await speakServer(c, resolveEngine());
    if (!state.stopFlag) setStatus("selesai");
  } catch (e) {
    setStatus(`gagal: ${e.message}`);
    $("listenHint").textContent = `TTS error — ${e.message}. Coba engine lain (Settings).`;
  } finally {
    setTransport(false);
    clearHighlight();
  }
}

/* ─────────────────────────── practice: mic + ASR ─────────────────────────── */
function pickMime() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  if (typeof MediaRecorder === "undefined") return "";
  return candidates.find((c) => MediaRecorder.isTypeSupported(c)) || "";
}

function setRecHint(t) { $("recHint").textContent = t; }

async function refreshMics() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
  try {
    const devices = (await navigator.mediaDevices.enumerateDevices())
      .filter((d) => d.kind === "audioinput");
    const sel = $("micSelect");
    sel.innerHTML = '<option value="">default sistem</option>' + devices.map((d, i) =>
      `<option value="${esc(d.deviceId)}">${esc(d.label || `Mikrofon ${i + 1}`)}</option>`).join("");
    if (state.micId && devices.some((d) => d.deviceId === state.micId)) sel.value = state.micId;
  } catch (_) { /* permission not granted yet */ }
}

function setupMeter(stream) {
  stopMeter();
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);
    state.meter = { ctx, analyser, buf, raf: 0 };
    const tick = () => {
      if (!state.meter) return;
      analyser.getByteTimeDomainData(buf);
      let peak = 0;
      for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
      $("recLevelBar").style.width = Math.min(100, Math.round((peak / 128) * 130)) + "%";
      state.meter.raf = requestAnimationFrame(tick);
    };
    tick();
  } catch (_) { state.meter = null; }
}

function stopMeter() {
  if (!state.meter) return;
  cancelAnimationFrame(state.meter.raf);
  try { state.meter.ctx.close(); } catch (_) {}
  state.meter = null;
  $("recLevelBar").style.width = "0%";
}

function fmtDb(db) {
  return Number.isFinite(db) ? `${db.toFixed(0)} dB` : "?";
}

function fmtTime(ms) {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function startSpeechRecognition() {
  // Web Speech API removed: transcription always goes through the local whisper server.
}

function stopSpeechRecognition() {
  // no-op (Web Speech API removed)
}

async function startRecording() {
  if (!currentChunk()) { $("practiceErr").textContent = "Pilih chunk dulu di tab Listen."; return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("practiceErr").textContent = "Browser ini tidak mendukung akses mikrofon (butuh http://localhost + Chrome/Firefox).";
    return;
  }
  $("practiceErr").textContent = "";
  state.lastTranscript = "";
  try {
    const constraints = {
      audio: state.micId
        ? { deviceId: { exact: state.micId }, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
        : { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    };
    state.stream = await navigator.mediaDevices.getUserMedia(constraints);
    refreshMics();
  } catch (e) {
    $("practiceErr").textContent = `Mikrofon tidak bisa diakses: ${e.message}`;
    return;
  }
  state.mimeType = pickMime();
  state.recParts = [];
  setupMeter(state.stream);
  try {
    state.mr = state.mimeType
      ? new MediaRecorder(state.stream, { mimeType: state.mimeType })
      : new MediaRecorder(state.stream);
  } catch (e) {
    $("practiceErr").textContent = `MediaRecorder gagal: ${e.message}`;
    state.stream.getTracks().forEach((t) => t.stop());
    return;
  }
  state.mr.ondataavailable = (ev) => { if (ev.data && ev.data.size) state.recParts.push(ev.data); };
  state.mr.start(250);
  state.recording = true;
  $("recBtn").classList.add("recording");
  $("recLabel").textContent = "Stop";
  state.recStart = Date.now();
  $("recTimer").textContent = "00:00";
  state.timerIv = setInterval(() => { $("recTimer").textContent = fmtTime(Date.now() - state.recStart); }, 250);
  setRecHint("merekam… ucapkan pelan, akhiri dengan kalimat lengkap.");
  setStatus("merekam");
}

async function stopRecording() {
  state.recording = false;
  clearInterval(state.timerIv);
  $("recBtn").classList.remove("recording");
  $("recLabel").textContent = "Record";
  setRecHint("memproses…");

  await new Promise((resolve) => {
    if (!state.mr || state.mr.state === "inactive") { resolve(); return; }
    state.mr.onstop = () => resolve();
    try { state.mr.stop(); } catch (_) { resolve(); }
  });
  stopSpeechRecognition();
  stopMeter();
  if (state.stream) { state.stream.getTracks().forEach((t) => t.stop()); state.stream = null; }

  const blob = new Blob(state.recParts, { type: state.mimeType || "audio/webm" });
  if (!blob.size) { setRecHint("rekaman kosong — coba lagi."); return; }

  if (state.lastRecordingUrl) URL.revokeObjectURL(state.lastRecordingUrl);
  state.lastRecordingUrl = URL.createObjectURL(blob);
  $("recPlayback").src = state.lastRecordingUrl;
  $("playbackRow").hidden = false;
  $("recDiag").textContent = "";

  let transcript = "";
  let diag = null;
  let serverError = "";
  try {
    const fd = new FormData();
    fd.append("file", blob, "recording.webm");
    fd.append("language", "en");
    const res = await fetch("/api/transcribe", { method: "POST", body: fd });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.error || `HTTP ${res.status}`);
    transcript = (j.text || "").trim();
    state.lastEngine = `faster-whisper · ${j.model}`;
    state.words = j.words || [];
    diag = j.audio || null;
  } catch (e) {
    serverError = e.message;
    $("practiceErr").textContent = `ASR server gagal: ${e.message}`;
    setRecHint("ulangi rekaman, atau cek Settings → status whisper.");
  }
  if (diag) {
    $("recDiag").textContent =
      `${Number(diag.duration || 0).toFixed(1)} dtk · level puncak ${fmtDb(diag.peak_db)}` +
      (Number(diag.peak_db) < -45 ? " (terlalu pelan)" : "");
  }
  const bare = transcript.replace(/[^\p{L}\p{N}]+/gu, "");
  if (!bare) {
    const info = diag
      ? ` Audio ${Number(diag.duration || 0).toFixed(1)} dtk, level puncak ${fmtDb(diag.peak_db)}.`
      : "";
    const low = diag && Number(diag.peak_db) < -45
      ? " Level audio sangat pelan — cek mikrofon/input device."
      : "";
    $("practiceErr").textContent =
      "Tidak ada transkrip." + info + low +
      (serverError ? ` Server: ${serverError}.` : "") +
      " Pastikan faster-whisper terpasang (Settings → status), lalu ucapkan lebih jelas/dekat ke mik.";
    setRecHint("belum ada hasil — tekan Record lagi.");
    return;
  }
  setRecHint(`terdengar: “${transcript}”`);
  await doCompare(transcript);
}

async function doCompare(transcript) {
  const c = currentChunk();
  if (!c) return;
  state.lastTranscript = transcript;
  try {
    const res = await postJSON("/api/compare", { reference: c.text, hypothesis: transcript });
    renderCompare(res, state.lastEngine);
    $("analyzeBtn").disabled = false;
    setStatus(`banding selesai · ${Math.round(res.stats.accuracy * 100)}% kecocokan`);
  } catch (e) {
    $("practiceErr").textContent = `banding gagal: ${e.message}`;
  }
}

function renderCompare(res, engine) {
  const s = res.stats;
  $("stAcc").textContent = Math.round(s.accuracy * 100) + "%";
  $("stOk").textContent = s.ok;
  $("stWrong").textContent = s.wrong;
  $("stMissed").textContent = s.missed;
  $("stExtra").textContent = s.extra;

  $("refWords").innerHTML = res.pairs.filter((p) => p.ref).map((p) => {
    const title = p.status === "wrong" ? ` title="terdengar: ${esc(p.hyp)}"` : "";
    return `<span class="w st-${p.status}"${title}>${esc(p.ref)}</span>`;
  }).join("");

  $("heardWords").innerHTML = res.pairs.filter((p) => p.hyp).map((p) =>
    `<span class="w st-${p.status}">${esc(p.hyp)}</span>`).join(" ");

  $("transcriptText").textContent = `transcript: ${res.hypothesisText || "—"}`;
  $("alignNote").textContent =
    `${engine ? `Engine: ${engine}. ` : ""}Angka berasal dari pengenalan suara (ASR), bukan penilaian fonetik: ` +
    `selisih bisa karena mik/derau atau kesalahan ASR, bukan selalu salah ucap. Pakai sebagai petunjuk, bukan vonis.`;
}

async function analyzeTranscript() {
  const c = currentChunk();
  if (!c || !state.lastTranscript) {
    $("feedbackBox").innerHTML = '<p class="muted">Rekam dulu sebelum minta koreksi.</p>';
    return;
  }
  $("feedbackBox").innerHTML = '<p class="muted">menganalisis…</p>';
  $("analyzeBtn").disabled = true;
  try {
    const res = await postJSON("/api/analyze", {
      kind: "transcript", text: state.lastTranscript, reference: c.text,
    });
    $("feedbackBox").innerHTML = renderRich(res.reply);
    state.lastFeedback = {
      ref: c.text, hyp: state.lastTranscript, text: res.reply,
      engine: res.engine || "rule",
    };
    $("saveLogBtn").disabled = false;
    setStatus(`koreksi dari ${res.engine === "offline" ? "mode lokal (rules)" : (res.engine || "rule")}`);
  } catch (e) {
    $("feedbackBox").innerHTML = `<p class="err">${esc(e.message)}</p>`;
  } finally {
    $("analyzeBtn").disabled = false;
  }
}

/* ─────────────────────────── error log ─────────────────────────── */
function persistLog() { localStorage.setItem("xl_log", JSON.stringify(state.log)); }

function renderLog() {
  const list = $("logList");
  $("logEmpty").style.display = state.log.length ? "none" : "";
  list.innerHTML = state.log.map((e) => `
    <li>
      <span class="when">${esc(e.when)}</span>
      <span class="s">${esc(e.ref)}</span>
      <span class="t">→ ${esc(e.hyp)}</span>
      <span class="r">${esc(e.rule)}</span>
    </li>`).join("");
}

function saveToLog() {
  const fb = state.lastFeedback;
  if (!fb) return;
  const rule = (fb.text.match(/Why:\s*(.+)/) || [, "lihat koreksi"])[1];
  state.log.unshift({
    when: new Date().toISOString().slice(0, 16).replace("T", " "),
    ref: fb.ref, hyp: fb.hyp, rule: rule.slice(0, 140),
  });
  state.log = state.log.slice(0, 80);
  persistLog(); renderLog();
  setStatus("disimpan ke error log");
}

function exportLog() {
  if (!state.log.length) { setStatus("log kosong"); return; }
  const md = [
    "# Error log — OEL", "",
    `> Dibuat: ${new Date().toLocaleString()}`, "",
    ...state.log.map((e) => [
      `- **${e.when}**`, `  - Kalimat: "${e.ref}"`, `  - Terdengar: "${e.hyp}"`,
      `  - Rule: ${e.rule}`, "",
    ].join("\n")),
  ].join("\n");
  const url = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url; a.download = "error-log.md"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/* ─────────────────────────── study ─────────────────────────── */
function studyStoreKey(title, count) { return `xl_study_v2_${title}_${count}`; }

function cleanupStudyStorage() {
  try {
    const doomed = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key && key.startsWith("xl_study_") && !key.startsWith("xl_study_v2_")) doomed.push(key);
    }
    doomed.forEach((key) => localStorage.removeItem(key));
  } catch (_) { /* storage blocked */ }
}

function loadStudyProgress(title, count) {
  try { return JSON.parse(localStorage.getItem(studyStoreKey(title, count)) || "{}"); }
  catch (_) { return {}; }
}

function saveStudyProgress() {
  const s = state.study;
  if (!s.title || !s.meta) return;
  try {
    localStorage.setItem(studyStoreKey(s.title, s.meta.count), JSON.stringify({
      answers: s.answers, revealed: s.revealed, index: s.index, best: s.best || 0,
    }));
  } catch (_) {}
}

function studyCorrectCount() {
  const s = state.study;
  let correct = 0;
  s.questions.forEach((q) => {
    if (s.revealed[q.n] && q.answer && s.answers[q.n] === q.answer) correct += 1;
  });
  return correct;
}

function setStudy(data) {
  state.study = {
    title: data.title, questions: data.questions, index: 0,
    answers: {}, revealed: {}, best: 0, meta: data,
  };
  const saved = loadStudyProgress(data.title, data.count);
  if (saved && saved.answers) {
    state.study.answers = saved.answers;
    state.study.revealed = saved.revealed || {};
    state.study.index = Math.min(saved.index || 0, data.questions.length - 1);
    state.study.best = Number(saved.best) || 0;
  }
  const diff = Object.entries(data.difficulty || {})
    .map(([k, v]) => `${k} ${v}`).join(" · ");
  $("studyMeta").textContent =
    `${data.count} soal${diff ? " · " + diff : ""}${data.hasKey ? "" : " · tanpa kunci"}`;
  $("studyEmpty").style.display = data.questions.length ? "none" : "";
  renderStudyList();
  renderStudyQuestion();
  setStatus(`study: ${data.title}`);
}

function renderStudyList() {
  const s = state.study;
  const list = $("studyList");
  list.innerHTML = s.questions.map((q, i) => {
    const revealed = s.revealed[q.n];
    const answer = s.answers[q.n];
    let badge = "";
    if (revealed && q.answer) {
      badge = `<span class="st ${answer === q.answer ? "ok" : "bad"}">${esc(answer || "—")}</span>`;
    } else if (answer) {
      badge = `<span class="st">${esc(answer)}</span>`;
    }
    return `<li data-i="${i}" class="${i === s.index ? "active" : ""}">`
      + `<span class="n">${String(q.n).padStart(2, "0")}</span>`
      + `<span>${esc(q.topic || "question")}</span>${badge}</li>`;
  }).join("");
  list.querySelectorAll("li").forEach((li) =>
    li.addEventListener("click", () => studyGo(Number(li.dataset.i))));
  updateStudyScore();
}

function updateStudyScore() {
  const s = state.study;
  let done = 0;
  const correct = studyCorrectCount();
  s.questions.forEach((q) => { if (s.revealed[q.n] && q.answer) done += 1; });
  const best = Math.max(s.best || 0, correct);
  $("studyScore").textContent =
    `${correct}/${s.questions.length} benar` +
    (best > 0 ? ` · best ${best}` : "") +
    (done ? ` · ${done} dikerjakan` : "");
}

function studyGo(i) {
  const s = state.study;
  if (!s.questions.length) return;
  s.index = Math.max(0, Math.min(i, s.questions.length - 1));
  renderStudyList();
  renderStudyQuestion();
  saveStudyProgress();
}

function renderStudyQuestion() {
  const s = state.study;
  const q = s.questions[s.index];
  if (!q) {
    $("studyIndex").textContent = "—";
    $("studyTags").textContent = "";
    $("studyQuestion").textContent = "Upload atau tempel practice set, lalu tekan “Muat soal”.";
    $("studyOptions").innerHTML = "";
    $("studyCheckBtn").disabled = true;
    $("studyPrevBtn").disabled = true;
    $("studyNextBtn").disabled = true;
    return;
  }
  $("studyIndex").textContent =
    `soal ${String(q.n).padStart(2, "0")} / ${String(s.questions.length).padStart(2, "0")}`;
  $("studyTags").textContent = [q.topic, q.difficulty].filter(Boolean).join(" · ");
  $("studyQuestion").textContent = q.text || "(soal kosong)";

  const chosen = s.answers[q.n];
  const revealed = Boolean(s.revealed[q.n]);
  $("studyOptions").innerHTML = Object.entries(q.options).map(([k, v]) => {
    let cls = "study-opt";
    if (chosen === k) cls += " selected";
    if (revealed && q.answer) {
      if (k === q.answer) cls += " correct";
      else if (chosen === k) cls += " wrong";
    }
    return `<button class="${cls}" data-k="${k}" ${revealed ? "disabled" : ""}>`
      + `<span class="k">${k}</span><span>${esc(v)}</span></button>`;
  }).join("");
  $("studyOptions").querySelectorAll(".study-opt").forEach((btn) =>
    btn.addEventListener("click", () => {
      if (revealed) return;
      s.answers[q.n] = btn.dataset.k;
      renderStudyQuestion();
      saveStudyProgress();
    }));

  $("studyCheckBtn").disabled = !chosen || revealed;
  $("studyPrevBtn").disabled = s.index === 0;
  $("studyNextBtn").disabled = s.index >= s.questions.length - 1;

  const fb = $("studyFeedback");
  if (revealed) {
    const ok = q.answer && chosen === q.answer;
    const verdict = q.answer
      ? `<p class="${ok ? "ok" : "bad"}">${ok ? "Benar." : `Salah — jawaban: ${esc(q.answer)}.`}</p>`
      : '<p class="muted">Kunci tidak tersedia di file.</p>';
    fb.innerHTML = verdict
      + (q.why ? `<p><b>Why:</b> ${esc(q.why)}</p>` : "")
      + (q.trap ? `<p><b>Trap:</b> ${esc(q.trap)}</p>` : "");
  } else if (chosen) {
    fb.innerHTML = `<p class="muted">Jawaban ${esc(chosen)} dipilih — tekan “Cek jawaban”.</p>`;
  } else {
    fb.innerHTML = '<p class="muted">Pilih jawaban A–D, lalu cek.</p>';
  }
}

function studyCheck() {
  const s = state.study;
  const q = s.questions[s.index];
  if (!q || !s.answers[q.n]) return;
  s.revealed[q.n] = true;
  s.best = Math.max(s.best || 0, studyCorrectCount());
  renderStudyList();
  renderStudyQuestion();
  saveStudyProgress();
  postStudyProgress();
}

function postStudyProgress() {
  const token = localStorage.getItem("xl_token");
  const s = state.study;
  if (!token || !s.title || !s.questions.length) return;
  fetch("/api/progress", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ set: s.title, correct: studyCorrectCount(), total: s.questions.length }),
  }).catch(() => {});
}

function studyReset() {
  const s = state.study;
  if (!s.questions.length) return;
  s.answers = {};
  s.revealed = {};
  s.index = 0;
  s.best = 0;
  saveStudyProgress();
  renderStudyList();
  renderStudyQuestion();
  setStatus("progres study direset — mulai dari soal 1");
}

async function loadStudy(text, filename) {
  if (!text.trim()) { $("studyErr").textContent = "Materi masih kosong."; return; }
  $("studyErr").textContent = "";
  setStatus("membaca soal…");
  try {
    const data = await postJSON("/api/study/parse", { text, filename });
    setStudy(data);
  } catch (e) {
    $("studyErr").textContent = e.message;
    setStatus("gagal membaca soal");
  }
}

function readStudyFile(file) {
  const reader = new FileReader();
  reader.onload = () => loadStudy(String(reader.result || ""), file.name);
  reader.onerror = () => { $("studyErr").textContent = "file tidak bisa dibaca"; };
  reader.readAsText(file, "utf-8");
}

/* ─────────────────────── rich feedback rendering ─────────────────────── */
function renderRich(raw) {
  if (!raw) return '<p class="muted">—</p>';
  const inline = (s) => s
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  const lines = esc(raw).split("\n");
  let html = "", para = [], listOpen = false, preOpen = false;
  const flush = () => { if (para.length) { html += `<p>${para.join("<br>")}</p>`; para = []; } };
  const closeList = () => { if (listOpen) { html += "</ul>"; listOpen = false; } };

  for (const line of lines) {
    if (/^```/.test(line)) {
      flush(); closeList(); html += preOpen ? "</pre>" : "<pre>"; preOpen = !preOpen; continue;
    }
    if (preOpen) { html += line + "\n"; continue; }
    const fb = line.match(/^(Fix|Why|Try):\s*(.*)$/);
    if (fb) {
      flush(); closeList();
      html += `<div class="fb ${fb[1]}"><span class="lbl">${fb[1]}</span>${inline(fb[2])}</div>`;
      continue;
    }
    if (/^#{1,4}\s+/.test(line)) {
      flush(); closeList();
      html += `<h4>${inline(line.replace(/^#{1,4}\s+/, ""))}</h4>`; continue;
    }
    if (/^([-*]|\d+\.)\s+/.test(line)) {
      flush();
      if (!listOpen) { html += "<ul>"; listOpen = true; }
      html += `<li>${inline(line.replace(/^([-*]|\d+\.)\s+/, ""))}</li>`; continue;
    }
    if (!line.trim()) { flush(); closeList(); continue; }
    para.push(inline(line));
  }
  flush(); closeList();
  if (preOpen) html += "</pre>";
  return html || '<p class="muted">—</p>';
}

/* ─────────────────────────── theme ─────────────────────────── */
function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("xl_theme", next); } catch (_) {}
  $("themeBtn").textContent = next === "light" ? "☀" : "☾";
  $("themeBtn").title = next === "light" ? "mode gelap" : "mode terang";
}

/* ─────────────────────────── wiring ─────────────────────────── */
function bind() {
  /* tabs */
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => {
      switchView(t.dataset.view);
      if (t.dataset.view === "practice") renderPracticeStage();
    }));

  /* home cards */
  document.querySelectorAll("[data-go]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const view = el.dataset.go;
      if (view === "learn") { location.href = "/learn"; return; }
      switchView(view);
      if (view === "practice") renderPracticeStage();
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.click(); }
    });
  });

  $("themeBtn").addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  });
  $("settingsBtn").addEventListener("click", () => switchView("settings"));

  /* listen */
  $("pickBtn").addEventListener("click", () => $("fileInput").click());
  $("fileInput").addEventListener("change", (e) => { if (e.target.files[0]) uploadFile(e.target.files[0]); });
  const drop = $("drop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault(); drop.classList.remove("over");
  }));
  drop.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });
  $("parsePasteBtn").addEventListener("click", parsePasted);
  $("wholeToggle").addEventListener("change", async (e) => {
    await saveSettings({ wholeText: e.target.checked }, true);
    $("parsePasteBtn").textContent = e.target.checked ? "Muat teks utuh" : "Potong jadi chunk";
    setStatus(e.target.checked ? "mode utuh: teks tidak dipecah" : "mode chunk: teks dipecah");
    if (!state.sourceText) return;
    try {
      applyResult(await postJSON("/api/parse", {
        text: state.sourceText, filename: state.filename || "pasted.txt",
        maxSentences: state.settings.maxSentences, maxWords: state.settings.maxWords,
        whole: e.target.checked,
      }));
    } catch (err) { $("listenErr").textContent = err.message; }
  });
  $("sampleBtn").addEventListener("click", () => {
    $("pasteBox").value = SAMPLE_TEXT;
    parsePasted();
  });

  /* study */
  $("studyPickBtn").addEventListener("click", () => $("studyFileInput").click());
  $("studyFileInput").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) readStudyFile(file);
  });
  const studyDrop = $("studyDrop");
  ["dragenter", "dragover"].forEach((ev) => studyDrop.addEventListener(ev, (e) => {
    e.preventDefault(); studyDrop.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((ev) => studyDrop.addEventListener(ev, (e) => {
    e.preventDefault(); studyDrop.classList.remove("over");
  }));
  studyDrop.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) readStudyFile(file);
  });
  $("studyLoadBtn").addEventListener("click", () => loadStudy($("studyBox").value, "pasted.txt"));
  $("studySampleBtn").addEventListener("click", async () => {
    try {
      const text = await fetch("/static/samples/practice-set-1.json").then((r) => r.text());
      $("studyBox").value = text;
      await loadStudy(text, "practice-set-1.json");
    } catch (e) { $("studyErr").textContent = e.message; }
  });
  $("studyCheckBtn").addEventListener("click", studyCheck);
  $("studyResetBtn").addEventListener("click", studyReset);
  $("studyPrevBtn").addEventListener("click", () => studyGo(state.study.index - 1));
  $("studyNextBtn").addEventListener("click", () => studyGo(state.study.index + 1));

  $("prevBtn").addEventListener("click", () => selectChunk(state.current - 1));
  $("nextBtn").addEventListener("click", () => selectChunk(state.current + 1));
  $("playBtn").addEventListener("click", playChunk);
  $("stopBtn").addEventListener("click", () => { stopPlayback(); setStatus("dihentikan"); });
  $("toPracticeBtn").addEventListener("click", () => {
    switchView("practice"); renderPracticeStage();
  });
  $("copyExportBtn").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(state.chunks.map((c) => c.text).join("\n\n")); setStatus("disalin ke clipboard"); }
    catch (_) { setStatus("clipboard diblokir browser"); }
  });

  $("engineSelect").addEventListener("change", (e) => {
    saveSettings({ ttsEngine: e.target.value });
    $("setTts").value = e.target.value;
    renderStage();
  });
  const rateChange = (val) => {
    state.settings.rate = Number(val);
    $("rateVal").textContent = Number(val).toFixed(2) + "×";
    $("setRateVal").textContent = Number(val).toFixed(2) + "×";
    $("rateRange").value = val; $("setRate").value = val;
    renderStage();
  };
  $("rateRange").addEventListener("input", (e) => rateChange(e.target.value));
  $("rateRange").addEventListener("change", (e) => saveSettings({ rate: Number(e.target.value) }));
  $("setRate").addEventListener("input", (e) => rateChange(e.target.value));
  $("setRate").addEventListener("change", (e) => saveSettings({ rate: Number(e.target.value) }));

  const pitchChange = (val) => {
    state.settings.pitch = Number(val);
    $("pitchVal").textContent = Number(val).toFixed(2) + "×";
    $("setPitchVal").textContent = Number(val).toFixed(2) + "×";
    $("pitchRange").value = val; $("setPitch").value = val;
    renderStage();
  };
  $("pitchRange").addEventListener("input", (e) => pitchChange(e.target.value));
  $("pitchRange").addEventListener("change", (e) => saveSettings({ pitch: Number(e.target.value) }));
  $("setPitch").addEventListener("input", (e) => pitchChange(e.target.value));
  $("setPitch").addEventListener("change", (e) => saveSettings({ pitch: Number(e.target.value) }));

  /* practice */
  $("recBtn").addEventListener("click", () => (state.recording ? stopRecording() : startRecording()));
  $("pPlayBtn").addEventListener("click", () => { switchView("listen"); playChunk(); });
  $("againBtn").addEventListener("click", () => { stopRecordingIfAny(); startRecording(); });
  $("analyzeBtn").addEventListener("click", analyzeTranscript);
  $("saveLogBtn").addEventListener("click", saveToLog);
  $("exportLogBtn").addEventListener("click", exportLog);
  $("clearLogBtn").addEventListener("click", () => {
    state.log = []; persistLog(); renderLog(); setStatus("log dibersihkan");
  });

  /* settings */
  $("setTts").addEventListener("change", (e) => {
    saveSettings({ ttsEngine: e.target.value });
    $("engineSelect").value = e.target.value;
    renderStage();
  });
  $("setAsr").addEventListener("change", (e) => saveSettings({ asrMode: e.target.value }));
  $("micSelect").addEventListener("change", (e) => {
    state.micId = e.target.value;
    if (state.micId) localStorage.setItem("xl_mic", state.micId);
    else localStorage.removeItem("xl_mic");
    setStatus(state.micId ? "input mikrofon diganti" : "mikrofon default sistem");
  });
  $("saveChunkBtn").addEventListener("click", async () => {
    await saveSettings({
      maxSentences: Math.max(1, Math.min(6, Number($("setSent").value) || 2)),
      maxWords: Math.max(8, Math.min(120, Number($("setWords").value) || 30)),
    });
    if ($("pasteBox").value.trim() || state.chunks.length) setStatus("aturan chunk disimpan");
  });
  $("micTestBtn").addEventListener("click", async () => {
    const out = $("micTestResult");
    out.textContent = " ukur level 2,5 dtk — bicara sekarang…";
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const Ctx = window.AudioContext || window.webkitAudioContext;
      const ctx = new Ctx();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      let peak = 0;
      const t0 = performance.now();
      await new Promise((resolve) => {
        const tick = () => {
          analyser.getByteTimeDomainData(buf);
          for (const v of buf) peak = Math.max(peak, Math.abs(v - 128));
          if (performance.now() - t0 < 2500) requestAnimationFrame(tick);
          else resolve();
        };
        tick();
      });
      stream.getTracks().forEach((t) => t.stop());
      try { await ctx.close(); } catch (_) {}
      const db = 20 * Math.log10(Math.max(peak / 128, 1e-4));
      out.textContent = db > -45
        ? ` mikrofon OK · level puncak ${db.toFixed(0)} dB`
        : ` level sangat pelan (${db.toFixed(0)} dB) — cek input device/volume`;
    } catch (e) { out.textContent = ` gagal: ${e.message}`; }
  });

  /* keyboard: left/right chunk, space play/stop */
  document.addEventListener("keydown", (e) => {
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
    if (e.key === "ArrowLeft") selectChunk(state.current - 1);
    else if (e.key === "ArrowRight") selectChunk(state.current + 1);
    else if (e.key === " ") { e.preventDefault(); state.playing ? stopPlayback() : playChunk(); }
  });
}

function stopRecordingIfAny() {
  if (state.recording) stopRecording();
}

function renderHealthBox() {
  const h = state.health;
  $("healthBox").textContent = h
    ? JSON.stringify({ tts: h.tts, asr: h.asr, ai: h.ai, settings: state.settings }, null, 2)
    : "—";
}

/* ─────────────────── laporkan kesalahan (GitHub / email) ─────────────────── */
const REPORT_ISSUES = "https://github.com/0xnhsec/OEL-Offline-English-Learning/issues/new";
const REPORT_EMAILS = ["0xnsec@intigriti.me", "0xnhsec@proton.me"];

function reportContext() {
  const active = document.querySelector(".view.active");
  const name = (active && active.id ? active.id.replace("view-", "") : "home");
  const map = { home: "Home", listen: "Listen", practice: "Practice", study: "Study", settings: "Settings" };
  return map[name] || name;
}

function issueLink(context) {
  const title = `[OEL] Laporan konten — ${context}`;
  const body = [
    "### Bagian yang salah",
    "(soal, kunci jawaban, penjelasan Why/Trap, atau teks bahasa Inggris yang keliru)",
    "",
    "### Di mana",
    `- Halaman: ${context}`,
    "- Modul / nomor soal: ",
    "",
    "### Yang seharusnya",
    "",
    "### Versi OEL",
    "`curl -s http://127.0.0.1:8765/api/version`",
    "",
  ].join("\n");
  return `${REPORT_ISSUES}?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
}

function mailLink(address, context) {
  const subject = encodeURIComponent(`[OEL] Laporan konten — ${context}`);
  const body = encodeURIComponent(
    `Halaman: ${context}\n\nBagian yang salah:\n\n\nYang seharusnya:\n\n`,
  );
  return `mailto:${address}?subject=${subject}&body=${body}`;
}

function openReport(context) {
  const ctx = context || reportContext();
  $("reportContext").textContent = ctx;
  $("reportIssue").href = issueLink(ctx);
  $("reportMail1").href = mailLink(REPORT_EMAILS[0], ctx);
  $("reportMail2").href = mailLink(REPORT_EMAILS[1], ctx);
  $("reportModal").hidden = false;
  document.body.classList.add("modal-open");
  $("reportClose").focus();
}

function closeReport() {
  $("reportModal").hidden = true;
  document.body.classList.remove("modal-open");
}

function bindReport() {
  document.querySelectorAll(".card-dots").forEach((button) => {
    const trigger = (event) => {
      event.preventDefault();
      event.stopPropagation();
      openReport(button.dataset.report);
    };
    button.addEventListener("click", trigger);
    button.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") trigger(event);
    });
  });
  if ($("reportClose")) $("reportClose").addEventListener("click", closeReport);
  if ($("reportBackdrop")) $("reportBackdrop").addEventListener("click", closeReport);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("reportModal") && !$("reportModal").hidden) closeReport();
  });
}

async function init() {
  bind();
  bindReport();
  cleanupStudyStorage();
  applyTheme(document.documentElement.dataset.theme);
  renderLog();
  renderStage();
  await Promise.all([loadSettings(), loadHealth()]);
  refreshMics();
  renderStage();

  const params = new URLSearchParams(location.search);
  if (params.get("sample")) {
    $("pasteBox").value = SAMPLE_TEXT;
    await parsePasted();
    switchView("listen");
  }
  const moduleId = params.get("module");
  if (moduleId) {
    try {
      const data = await fetch(`/api/modules/${encodeURIComponent(moduleId)}`).then((r) => r.json());
      if (data && data.questions && data.questions.length) {
        setStudy(data);
        switchView("study");
      }
    } catch (_) { /* ignore: stay on home */ }
  }
  if (params.get("view")) {
    switchView(params.get("view"));
    if (params.get("view") === "practice") renderPracticeStage();
  }
  setStatus("siap — pilih Learn 101 atau Speaking & Listening");
}

/* expose a tiny debug/test surface (used by tests/e2e.py and the console) */
window.XL = {
  state, SAMPLE_TEXT, switchView, renderStage, renderPracticeStage,
  playChunk, stopPlayback, doCompare, analyzeTranscript, parsePasted,
  loadStudy, setStudy, studyCheck, studyGo, studyReset, applyTheme,
  loadHealth, loadSettings, renderLog, openReport, closeReport,
};

init();
