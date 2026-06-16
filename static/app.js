const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const statusEl = $("#status");
const remoteEl = $("#remote");
const setupEl = $("#setup");
const setupError = $("#setup-error");
const setupDesc = $("#setup-desc");
const discoveringEl = $("#discovering");
const manualSetupEl = $("#manual-setup");
const toastEl = $("#toast");

let connected = false;
let platform = null;
const lastKeyAt = new Map();

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg).join(", ")
      : detail || res.statusText;
    throw new Error(msg);
  }
  return data;
}

function showToast(msg, duration = 2000) {
  toastEl.textContent = msg;
  toastEl.classList.remove("hidden");
  setTimeout(() => toastEl.classList.add("hidden"), duration);
}

function showError(msg) {
  setupError.textContent = msg;
  setupError.classList.remove("hidden");
}

function clearError() {
  setupError.classList.add("hidden");
}

function setDiscovering(active, message = "Looking for TVs nearby") {
  if (active) {
    discoveringEl.classList.remove("hidden");
    discoveringEl.querySelector("span").textContent = message;
    manualSetupEl.classList.add("hidden");
  } else {
    discoveringEl.classList.add("hidden");
    manualSetupEl.classList.remove("hidden");
  }
}

let voiceBusy = false;
let voiceStatusData = null;
let mediaStream = null;
let mediaRecorder = null;
let audioChunks = [];
let recordMimeType = "";
let recordStartedAt = 0;
let isRecording = false;

function setConnected(info) {
  connected = true;
  platform = info.platform;
  const label =
    info.device?.["friendly-device-name"] ||
    info.device?.["model-name"] ||
    info.host;
  statusEl.textContent = `${label} · ${info.host}`;
  statusEl.classList.add("connected");
  remoteEl.classList.remove("hidden");
  setupEl.classList.add("hidden");
  setDiscovering(false);

  const authSection = $("#auth-section");
  if (info.platform === "vidaa") {
    authSection.classList.remove("hidden");
  } else {
    authSection.classList.add("hidden");
  }

  loadVoiceStatus();
}

function setDisconnected() {
  connected = false;
  platform = null;
  statusEl.textContent = "Not connected";
  statusEl.classList.remove("connected");
  remoteEl.classList.add("hidden");
  setupEl.classList.remove("hidden");
}

async function connectTo(host, platformValue) {
  clearError();
  const btn = $("#connect-btn");
  btn.disabled = true;
  btn.textContent = "Connecting…";

  try {
    const data = await api("/connect", {
      method: "POST",
      body: JSON.stringify({
        host,
        platform: platformValue,
        use_ssl: $("#use-ssl").checked,
      }),
    });
    setConnected(data);
    showToast("Connected!");
    return true;
  } catch (err) {
    showError(err.message);
    return false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Connect";
  }
}

function renderScanResults(tvs) {
  const resultsEl = $("#scan-results");
  resultsEl.innerHTML = "";

  if (tvs.length === 0) {
    resultsEl.classList.add("hidden");
    return;
  }

  resultsEl.classList.remove("hidden");
  tvs.forEach((tv) => {
    const item = document.createElement("button");
    item.className = "scan-item";
    const name = tv.name || tv.model || tv.ip;
    item.textContent = `${name} — ${tv.ip}`;
    item.addEventListener("click", async () => {
      $("#tv-ip").value = tv.ip;
      $("#platform").value = tv.platform === "roku" ? "roku" : "vidaa";
      await connectTo(tv.ip, tv.platform);
    });
    resultsEl.appendChild(item);
  });
}

async function discoverAndConnect(platformFilter = "roku", autoConnect = true) {
  setDiscovering(true, "Searching for your Roku TV…");
  setupDesc.textContent = "Looking on your Wi‑Fi network…";
  clearError();

  try {
    const data = await api(`/scan?platform=${platformFilter}`);

    if (data.tvs.length === 0) {
      setDiscovering(false);
      setupDesc.textContent = "No TV found automatically. Enter your TV IP below, or tap Scan.";
      showError("Couldn't find your TV on Wi‑Fi. Is it turned on?");
      return;
    }

    renderScanResults(data.tvs);
    const tv = data.tvs[0];
    $("#tv-ip").value = tv.ip;
    $("#platform").value = "roku";

    if (autoConnect && data.tvs.length === 1) {
      setDiscovering(true, `Found ${tv.name || "Roku TV"} — connecting…`);
      const ok = await connectTo(tv.ip, "roku");
      if (!ok) setDiscovering(false);
    } else {
      setDiscovering(false);
      setupDesc.textContent = `${data.tvs.length} TVs found. Tap one to connect.`;
    }
  } catch (err) {
    setDiscovering(false);
    setupDesc.textContent = "Auto-discovery failed. Enter your TV IP manually.";
    showError(err.message);
  }
}

async function sendKey(key) {
  const now = Date.now();
  const prev = lastKeyAt.get(key) || 0;
  if (now - prev < 220) return;
  lastKeyAt.set(key, now);

  try {
    await api("/key", { method: "POST", body: JSON.stringify({ key }) });
    if (key === "home") showToast("Home");
  } catch (err) {
    showToast(`Error: ${err.message}`);
  }
}

async function launchApp(app) {
  try {
    await api("/app", { method: "POST", body: JSON.stringify({ app }) });
    showToast(`Launching ${app}…`);
  } catch (err) {
    showToast(`Error: ${err.message}`);
  }
}

function setVoiceResult(message) {
  const el = $("#voice-result");
  if (!message) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = message;
  el.classList.remove("hidden");
}

function setVoiceTranscript(text) {
  const el = $("#voice-transcript");
  if (!text) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = `Heard: “${text}”`;
  el.classList.remove("hidden");
}

function updateVoiceStatusLine(message) {
  $("#voice-status").textContent = message;
}

async function loadVoiceStatus() {
  const statusEl = $("#voice-status");
  const hintEl = $("#voice-hint");
  try {
    voiceStatusData = await api("/voice/status");
    const agent = voiceStatusData.agent && voiceStatusData.agent !== "rules" ? "AI" : "Basic";
    const mode = voiceStatusData.transcribe ? "Groq Whisper" : "browser speech";

    if (!window.isSecureContext && voiceStatusData.https_url) {
      statusEl.textContent = "Mic needs HTTPS";
      hintEl.innerHTML = `For voice, open <a href="${voiceStatusData.https_url}" class="voice-link">${voiceStatusData.https_url}</a> and accept the certificate warning once.`;
      return;
    }

    statusEl.textContent = `${agent} ready · ${mode}`;
    if (voiceStatusData.transcribe) {
      hintEl.textContent = "Hold the mic, speak, then release. Example: “Play Inception”.";
    }
  } catch {
    statusEl.textContent = "Assistant unavailable";
  }
}

async function runVoiceCommand(text) {
  const command = text.trim();
  if (!command || voiceBusy) return;

  voiceBusy = true;
  const sendBtn = $("#voice-send-btn");
  const micBtn = $("#voice-mic-btn");
  sendBtn.disabled = true;
  micBtn.disabled = true;
  setVoiceResult(
    "Working… opening app, searching, and pressing play.\nThis usually takes 20–40 seconds — keep the remote open.",
  );

  try {
    const data = await api("/voice", {
      method: "POST",
      body: JSON.stringify({ text: command }),
    });
    let msg = data.message;
    if (data.plan) {
      msg = [
        data.plan.summary || data.message,
        data.plan.search_reason ? `Search: ${data.plan.search_reason}` : "",
        data.plan.app_reason ? `App: ${data.plan.app_reason}` : "",
        data.search_query ? `Typing: “${data.search_query}”` : "",
        data.search_steps ? data.search_steps : "",
      ].filter(Boolean).join("\n");
    } else if (data.search_steps) {
      msg += `\n${data.search_steps}`;
    }
    setVoiceResult(msg);
    showToast(data.plan?.summary || data.message, 3600);
  } catch (err) {
    setVoiceResult(`Error: ${err.message}`);
    showToast(`Error: ${err.message}`);
  } finally {
    voiceBusy = false;
    sendBtn.disabled = false;
    micBtn.disabled = false;
  }
}

function pickRecorderMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/mp4",
    "audio/aac",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
}

function extensionForMime(mime) {
  if (mime.includes("mp4") || mime.includes("aac")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

async function ensureMicrophone() {
  if (!window.isSecureContext) {
    const url = voiceStatusData?.https_url;
    throw new Error(url ? `Mic requires HTTPS: ${url}` : "Mic requires HTTPS");
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Microphone not supported in this browser.");
  }
  if (!mediaStream) {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
  }
}

async function startRecording() {
  if (voiceBusy || isRecording) return;
  await ensureMicrophone();

  recordMimeType = pickRecorderMimeType();
  if (!recordMimeType) {
    throw new Error("Audio recording not supported on this device.");
  }

  audioChunks = [];
  mediaRecorder = new MediaRecorder(mediaStream, { mimeType: recordMimeType });
  mediaRecorder.addEventListener("dataavailable", (e) => {
    if (e.data.size > 0) audioChunks.push(e.data);
  });

  mediaRecorder.start(250);
  isRecording = true;
  recordStartedAt = Date.now();
  $("#voice-mic-btn").classList.add("listening");
  updateVoiceStatusLine("Listening… hold and speak");
  setVoiceTranscript("");
}

async function stopRecordingAndTranscribe() {
  if (!isRecording || !mediaRecorder) return;

  const micBtn = $("#voice-mic-btn");
  const elapsed = Date.now() - recordStartedAt;
  isRecording = false;
  micBtn.classList.remove("listening");

  if (elapsed < 450) {
    if (mediaRecorder.state !== "inactive") mediaRecorder.stop();
    updateVoiceStatusLine("Hold longer and speak clearly");
    showToast("Hold the mic button longer while speaking.");
    await loadVoiceStatus();
    return;
  }

  updateVoiceStatusLine("Transcribing…");

  const recorder = mediaRecorder;
  const blob = await new Promise((resolve) => {
    recorder.addEventListener("stop", () => {
      resolve(new Blob(audioChunks, { type: recordMimeType || "audio/webm" }));
    }, { once: true });
    if (recorder.state !== "inactive") recorder.stop();
  });

  if (blob.size < 800) {
    showToast("No audio captured — try again.");
    await loadVoiceStatus();
    return;
  }

  voiceBusy = true;
  micBtn.disabled = true;
  $("#voice-send-btn").disabled = true;

  try {
    const ext = extensionForMime(recordMimeType);
    const form = new FormData();
    form.append("audio", blob, `voice.${ext}`);

    const res = await fetch("/api/voice/transcribe", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      throw new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : detail || res.statusText);
    }

    const text = (data.text || "").trim();
    if (!text) throw new Error("No speech detected");

    $("#voice-input").value = text;
    setVoiceTranscript(text);
    await runVoiceCommand(text);
  } catch (err) {
    setVoiceResult(`Voice error: ${err.message}`);
    showToast(err.message);
    await loadVoiceStatus();
  } finally {
    voiceBusy = false;
    micBtn.disabled = false;
    $("#voice-send-btn").disabled = false;
    if (!isRecording) await loadVoiceStatus();
  }
}

function setupVoiceAssistant() {
  const micBtn = $("#voice-mic-btn");

  $("#voice-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#voice-input");
    const text = input.value.trim();
    if (!text) return;
    await runVoiceCommand(text);
    input.value = "";
  });

  const begin = async (e) => {
    e.preventDefault();
    if (voiceBusy) return;
    try {
      await startRecording();
    } catch (err) {
      showToast(err.message);
      await loadVoiceStatus();
    }
  };

  const end = (e) => {
    e.preventDefault();
    stopRecordingAndTranscribe();
  };

  micBtn.addEventListener("pointerdown", begin);
  micBtn.addEventListener("pointerup", end);
  micBtn.addEventListener("pointerleave", end);
  micBtn.addEventListener("pointercancel", end);
  micBtn.addEventListener("contextmenu", (e) => e.preventDefault());
}

function bindKeys() {
  $$("[data-key]").forEach((btn) => {
    const key = btn.dataset.key;
    const press = () => {
      btn.classList.add("pressed");
      sendKey(key);
    };
    const release = () => btn.classList.remove("pressed");

    btn.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      press();
    });
    btn.addEventListener("pointerup", release);
    btn.addEventListener("pointerleave", release);
    btn.addEventListener("pointercancel", release);
  });

  $$("[data-app]").forEach((btn) => {
    btn.addEventListener("click", () => launchApp(btn.dataset.app));
  });
}

$("#connect-btn").addEventListener("click", async () => {
  const host = $("#tv-ip").value.trim();
  if (!host) {
    showError("Enter your TV's IP address.");
    return;
  }
  await connectTo(host, $("#platform").value);
});

$("#scan-btn").addEventListener("click", async () => {
  const btn = $("#scan-btn");
  btn.disabled = true;
  btn.textContent = "Scanning…";
  clearError();
  setDiscovering(true);

  try {
    const platformFilter = $("#platform").value === "vidaa" ? "vidaa" : "roku";
    const data = await api(`/scan?platform=${platformFilter}`);
    if (data.tvs.length === 0) {
      showToast("No TVs found on your network.");
    } else {
      renderScanResults(data.tvs);
      setupDesc.textContent = `${data.tvs.length} TV(s) found. Tap one to connect.`;
    }
  } catch (err) {
    showToast(`Scan failed: ${err.message}`);
  } finally {
    setDiscovering(false);
    btn.disabled = false;
    btn.textContent = "Scan";
  }
});

$("#auth-start-btn").addEventListener("click", async () => {
  try {
    await api("/auth/start", { method: "POST" });
    showToast("Check your TV for the PIN.");
  } catch (err) {
    showToast(err.message);
  }
});

$("#auth-verify-btn").addEventListener("click", async () => {
  const code = $("#auth-code").value.trim();
  if (code.length !== 4) {
    showToast("Enter the 4-digit PIN.");
    return;
  }
  try {
    await api("/auth/verify", { method: "POST", body: JSON.stringify({ code }) });
    showToast("Paired successfully!");
  } catch (err) {
    showToast(err.message);
  }
});

$("#settings-btn").addEventListener("click", () => {
  setDisconnected();
  discoverAndConnect("roku", false);
});

async function init() {
  bindKeys();
  setupVoiceAssistant();
  try {
    const cfg = await api("/config");
    if (cfg.host && cfg.platform) {
      $("#tv-ip").value = cfg.host;
      $("#platform").value = cfg.platform === "roku" ? "roku" : cfg.platform === "vidaa" ? "vidaa" : "auto";
      if (cfg.use_ssl !== undefined) $("#use-ssl").checked = cfg.use_ssl;

      setDiscovering(true, "Reconnecting to your TV…");
      try {
        const data = await api("/connect", {
          method: "POST",
          body: JSON.stringify({
            host: cfg.host,
            platform: cfg.platform,
            use_ssl: cfg.use_ssl ?? true,
          }),
        });
        setConnected(data);
        return;
      } catch {
        /* fall through to auto-discovery */
      }
    }
  } catch {
    /* server not ready */
  }

  await discoverAndConnect("roku", true);
}

init();