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
let savedConnection = null;
const lastKeyAt = new Map();

async function api(path, options = {}, timeoutMs = 0) {
  const controller = timeoutMs > 0 ? new AbortController() : null;
  const timer = controller
    ? setTimeout(() => controller.abort(), timeoutMs)
    : null;

  try {
    const res = await fetch(`/api${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
      signal: controller?.signal,
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
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("Request timed out — keep the remote open and try again.");
    }
    throw err;
  } finally {
    if (timer) clearTimeout(timer);
  }
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
  } else {
    discoveringEl.classList.add("hidden");
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
  savedConnection = { host: info.host, platform: info.platform };
  try {
    localStorage.setItem("tv-connection", JSON.stringify(savedConnection));
  } catch {
    /* private mode */
  }
  hideOffline();
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

async function checkServerHealth() {
  try {
    return await api("/health", {}, 5000);
  } catch (err) {
    throw new Error(
      err.message.includes("fetch") || err.message.includes("Failed")
        ? "Can't reach the remote server on this address."
        : err.message,
    );
  }
}

async function loadSavedTvHint() {
  try {
    const cfg = await api("/config");
    if (cfg.host) {
      $("#tv-ip").value = cfg.host;
      if (cfg.platform === "roku") $("#platform").value = "roku";
      return cfg.host;
    }
  } catch {
    /* server offline */
  }
  return null;
}

async function discoverAndConnect(platformFilter = "roku", autoConnect = true) {
  setDiscovering(true, "Searching for your Roku TV…");
  setupDesc.textContent = "Looking on your Wi‑Fi network…";
  clearError();

  try {
    const data = await api(`/scan?platform=${platformFilter}`, {}, 45000);

    if (data.tvs.length === 0) {
      const saved = data.saved_host || $("#tv-ip").value.trim() || (await loadSavedTvHint());
      if (saved) {
        setDiscovering(true, `Scan empty — connecting to ${saved}…`);
        const ok = await connectTo(saved, platformFilter);
        if (ok) return;
      }
      setDiscovering(false);
      setupDesc.textContent = data.hint || (saved
        ? `No TV found via scan. IP ${saved} is filled in — tap Connect.`
        : "No TV found. Enter your TV IP below.");
      showError(
        data.hint || (saved
          ? `Scan found nothing. Your TV may still be at ${saved} — tap Connect.`
          : "Couldn't find your TV on Wi‑Fi. Is it on and on the same network?"),
      );
      if (saved) $("#tv-ip").value = saved;
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
    const saved = await loadSavedTvHint();
    setDiscovering(false);
    setupDesc.textContent = saved
      ? `Search failed. Try last known IP ${saved} below.`
      : "Auto-discovery failed. Enter your TV IP manually.";
    let hint = err.message;
    if (err.message.includes("fetch") || err.message.includes("Failed") || err.message.includes("remote server")) {
      hint =
        "Can't reach the remote server. On your Mac run: cd hisense-remote && ./start.sh — then open the HTTPS URL it prints.";
    } else if (err.message.includes("timed out")) {
      hint = "Scan timed out. Tap Connect with your TV IP, or try Scan again.";
    }
    showError(
      saved
        ? `${hint} Or tap Connect with ${saved}.`
        : hint,
    );
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
    hideOffline();
  } catch (err) {
    showToast(`Error: ${err.message}`);
    markOffline("Server unreachable — tap Retry");
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
    const brain = voiceStatusData.llm ? (voiceStatusData.brain || "AI") : "rules-only";
    const mic = voiceStatusData.transcribe ? "Groq Whisper" : "text";

    if (!window.isSecureContext && voiceStatusData.https_url) {
      statusEl.textContent = "Mic needs HTTPS";
      hintEl.innerHTML = `For voice, open <a href="${voiceStatusData.https_url}" class="voice-link">${voiceStatusData.https_url}</a> and accept the certificate warning once.`;
      return;
    }

    const mode = voiceStatusData.mode === "search_only" ? "search only" : "voice";
    statusEl.textContent = `${brain} · ${mic} · ${mode}`;
    if (voiceStatusData.transcribe) {
      hintEl.textContent =
        "Hold the mic and speak. Your exact words are typed into Roku Search — then you browse on the remote.";
    }
  } catch {
    statusEl.textContent = "Voice search unavailable";
  }
}

function formatAssistantResult(data) {
  if (!data.success) {
    return data.message || "Could not complete that command.";
  }

  if (data.mode === "fast") {
    return data.message;
  }

  if (data.mode === "search") {
    const query = data.search_query || data.title || data.message;
    const parts = [`✓ Typed in Roku Search: "${query}"`];
    if (data.user_action) {
      parts.push(data.user_action);
    }
    if (data.search_steps) {
      parts.push("", data.search_steps);
    }
    return parts.join("\n");
  }

  return data.message;
}

function assistantLoadingMessage(text) {
  const lowered = text.trim().toLowerCase();
  if (
    /\b(watch|find|search(?:\s+for)?|show(?:\s+me)?)\b/.test(lowered) ||
    /\bplay\s+\S/.test(lowered)
  ) {
    return "Opening Roku Search and typing your query…";
  }
  if (
    /^(press|tap|hit|click|open|launch|start|go home|home|volume|mute|pause|play|type|enter)\b/.test(
      lowered,
    )
  ) {
    return "Running…";
  }
  if (lowered.length > 0) {
    return "Opening Roku Search and typing your query…";
  }
  return "Running…";
}

async function runVoiceCommand(text) {
  const command = text.trim();
  if (!command || voiceBusy) return;

  voiceBusy = true;
  const sendBtn = $("#voice-send-btn");
  const micBtn = $("#voice-mic-btn");
  sendBtn.disabled = true;
  micBtn.disabled = true;
  setVoiceResult(assistantLoadingMessage(command));

  try {
    const data = await api(
      "/voice",
      {
        method: "POST",
        body: JSON.stringify({ text: command }),
      },
      60000,
    );
    setVoiceResult(formatAssistantResult(data));
    const toastMsg =
      data.mode === "search" && data.search_query
        ? `Search: ${data.search_query}`
        : data.message;
    showToast(toastMsg, 3600);
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
    const data = await api(`/scan?platform=${platformFilter}`, {}, 45000);
    if (data.tvs.length === 0) {
      showToast("No TVs found on your network.");
    } else {
      renderScanResults(data.tvs);
      setupDesc.textContent = `${data.tvs.length} TV(s) found. Tap one to connect.`;
    }
  } catch (err) {
    const saved = $("#tv-ip").value.trim();
    let msg = err.message;
    if (err.message.includes("fetch") || err.message.includes("Failed") || err.message.includes("remote server")) {
      msg = "Can't reach server — run ./start.sh on your Mac";
    } else if (saved) {
      msg = `${err.message} — try Connect with ${saved}`;
    }
    showError(msg);
    showToast(`Scan failed: ${msg}`);
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
    const health = await checkServerHealth();
    if (health?.server_ip) {
      setupDesc.textContent = `Server at ${health.server_ip}. Connecting to your TV…`;
    }
    const cfg = await api("/config");
    if (cfg.host && cfg.platform) {
      $("#tv-ip").value = cfg.host;
      $("#platform").value = cfg.platform === "roku" ? "roku" : cfg.platform === "vidaa" ? "vidaa" : "auto";
      if (cfg.use_ssl !== undefined) $("#use-ssl").checked = cfg.use_ssl;

      if (cfg.lan_ok === false) {
        setupDesc.textContent = "Server may lack Wi‑Fi — trying saved TV IP anyway…";
      }

      setDiscovering(true, `Connecting to ${cfg.host}…`);
      const ok = await connectTo(
        cfg.host,
        cfg.platform === "roku" ? "roku" : cfg.platform,
      );
      if (ok) return;

      setDiscovering(false);
      setupDesc.textContent = `Couldn't connect to ${cfg.host}. Try Scan or Connect again.`;
    }
  } catch {
    setupDesc.textContent = "Remote server not reachable. Start it with ./start.sh on your computer.";
    showError("Can't reach the remote server. Run ./start.sh on your Mac, then reload this page.");
    setDiscovering(false);
    await loadSavedTvHint();
    return;
  }

  await discoverAndConnect("roku", false);
}

function markOffline(msg) {
  const banner = $("#offline-banner");
  const msgEl = $("#offline-msg");
  if (msgEl) msgEl.textContent = msg || "Server offline";
  banner?.classList.remove("hidden");
  statusEl.classList.remove("connected");
  statusEl.classList.add("reconnecting");
  statusEl.textContent = "Reconnecting…";
}

function hideOffline() {
  $("#offline-banner")?.classList.add("hidden");
  statusEl.classList.remove("reconnecting");
}

function loadSavedConnection() {
  try {
    const raw = localStorage.getItem("tv-connection");
    if (raw) return JSON.parse(raw);
  } catch {
    /* ignore */
  }
  return null;
}

async function tryReconnect() {
  const saved = savedConnection || loadSavedConnection();
  if (!saved?.host) return false;

  statusEl.textContent = "Reconnecting…";
  statusEl.classList.add("reconnecting");
  try {
    const health = await checkServerHealth();
    if (!health.ok) return false;
    const data = await api("/connect", {
      method: "POST",
      body: JSON.stringify({
        host: saved.host,
        platform: saved.platform || "roku",
        use_ssl: true,
      }),
    });
    setConnected(data);
    showToast("Reconnected");
    return true;
  } catch {
    markOffline("Mac asleep or server stopped — wake Mac, then Retry");
    return false;
  }
}

function setupConnectionWatchdog() {
  const retryBtn = $("#offline-retry");
  retryBtn?.addEventListener("click", () => tryReconnect());

  setInterval(async () => {
    if (!connected) return;
    try {
      await api("/health", {}, 4000);
      hideOffline();
    } catch {
      markOffline("Connection lost — tap Retry");
    }
  }, 25000);

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && connected) {
      tryReconnect();
    }
  });
}

function setupTabs() {
  const panels = {
    remote: $("#tab-remote"),
    voice: $("#tab-voice"),
  };

  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      $$(".nav-btn").forEach((b) => b.classList.toggle("active", b === btn));
      Object.entries(panels).forEach(([name, el]) => {
        if (!el) return;
        if (name === tab) {
          el.hidden = false;
          el.classList.add("active");
        } else {
          el.hidden = true;
          el.classList.remove("active");
        }
      });
    });
  });
}

function setupPwa() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  const banner = $("#install-banner");
  const installBtn = $("#install-btn");
  const dismissBtn = $("#install-dismiss");
  let deferredPrompt = null;

  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;

  if (isStandalone || localStorage.getItem("pwa-dismiss") === "1") {
    return;
  }

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    banner.classList.remove("hidden");
  });

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  if (isIOS && !isStandalone) {
    banner.classList.remove("hidden");
    installBtn.textContent = "How";
    installBtn.onclick = () => {
      showToast("Safari → Share → Add to Home Screen", 5000);
    };
  }

  installBtn?.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    banner.classList.add("hidden");
  });

  dismissBtn?.addEventListener("click", () => {
    banner.classList.add("hidden");
    localStorage.setItem("pwa-dismiss", "1");
  });
}

setupTabs();
setupPwa();
setupConnectionWatchdog();
init();