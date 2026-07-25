import {
  discover,
  getTvIp,
  isSecureContextBlocking,
  launchApp,
  playTitle,
  probeTv,
  sendKey,
  setTvIp,
} from "./direct.js";

const $ = (s) => document.querySelector(s);
const statusEl = $("#status");
const remoteEl = $("#remote");
const connectPanel = $("#connect-panel");
const toastEl = $("#toast");
const errEl = $("#connect-error");

let tvIp = "";
let lastKeyAt = 0;

function toast(msg, ms = 2000) {
  toastEl.textContent = msg;
  toastEl.classList.remove("hidden");
  setTimeout(() => toastEl.classList.add("hidden"), ms);
}

function showErr(msg) {
  errEl.textContent = msg;
  errEl.classList.remove("hidden");
}

function clearErr() {
  errEl.classList.add("hidden");
}

function setConnected(info) {
  tvIp = info.ip;
  setTvIp(info.ip);
  statusEl.textContent = `${info.name} · ${info.ip}`;
  statusEl.classList.add("connected");
  remoteEl.classList.remove("hidden");
  connectPanel.classList.add("hidden");
}

async function connect(ip) {
  clearErr();
  const hit = await probeTv(ip);
  if (!hit) {
    showErr(`No Roku at ${ip}. Check IP in Settings → Network → About.`);
    return false;
  }
  setConnected(hit);
  toast("Connected direct");
  return true;
}

function bindKeys() {
  document.querySelectorAll("[data-key]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!tvIp) return;
      const now = Date.now();
      if (now - lastKeyAt < 200) return;
      lastKeyAt = now;
      btn.classList.add("pressed");
      setTimeout(() => btn.classList.remove("pressed"), 120);
      try {
        await sendKey(tvIp, btn.dataset.key);
      } catch (e) {
        toast(e.message, 3500);
      }
    });
  });

  document.querySelectorAll("[data-app]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!tvIp) return;
      try {
        await launchApp(tvIp, btn.dataset.app);
        toast(`Opening ${btn.dataset.app}`);
      } catch (e) {
        toast(e.message, 3500);
      }
    });
  });
}

$("#connect-direct")?.addEventListener("click", async () => {
  const ip = $("#tv-ip-direct").value.trim();
  if (!ip) {
    showErr("Enter your TV IP.");
    return;
  }
  $("#connect-direct").disabled = true;
  await connect(ip);
  $("#connect-direct").disabled = false;
});

$("#scan-direct")?.addEventListener("click", async () => {
  clearErr();
  $("#scan-direct").disabled = true;
  $("#scan-direct").textContent = "…";
  statusEl.textContent = "Scanning…";
  try {
    const tvs = await discover();
    if (!tvs.length) {
      showErr("No TV found. Enter IP manually.");
      statusEl.textContent = "Not found";
      return;
    }
    $("#tv-ip-direct").value = tvs[0].ip;
    await connect(tvs[0].ip);
  } finally {
    $("#scan-direct").disabled = false;
    $("#scan-direct").textContent = "Find";
  }
});

$("#play-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = $("#play-input").value.trim();
  if (!title || !tvIp) return;
  toast(`Playing “${title}”…`, 4000);
  try {
    await playTitle(tvIp, title);
    toast("Sent to TV");
  } catch (err) {
    toast(err.message, 4000);
  }
});

function init() {
  if (isSecureContextBlocking()) {
    const host = location.hostname;
    const warn = $("#https-warn");
    warn.classList.remove("hidden");
    warn.innerHTML =
      `<strong>Use HTTP for direct mode.</strong> Safari blocks HTTPS pages from talking to the TV. `
      + `Open <a href="http://${host}:8080/direct" style="color:#7ee8ff">http://${host}:8080/direct</a> `
      + `or install this page from that URL to your home screen.`;
  }

  const saved = getTvIp();
  if (saved) {
    $("#tv-ip-direct").value = saved;
    if (!isSecureContextBlocking()) {
      connect(saved);
    }
  }

  bindKeys();
}

if ("serviceWorker" in navigator && location.protocol === "http:") {
  navigator.serviceWorker.register("/static/sw-direct.js", { scope: "/" }).catch(() => {});
}

init();
