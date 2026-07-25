/**
 * Roku ECP client — runs in the phone browser, no home server.
 * Requires HTTP (not HTTPS) or native shell to avoid mixed-content blocks.
 */

const TV_IP_KEY = "roku-direct-ip";

const KEY_MAP = {
  power: "PowerOff",
  up: "Up",
  down: "Down",
  left: "Left",
  right: "Right",
  ok: "Select",
  back: "Back",
  home: "Home",
  volume_up: "VolumeUp",
  volume_down: "VolumeDown",
  mute: "VolumeMute",
  play: "Play",
  pause: "Pause",
  rewind: "Rev",
  fast_forward: "Fwd",
};

const APPS = {
  netflix: "12",
  youtube: "837",
  amazon: "13",
  prime: "13",
  disney: "291097",
  hulu: "2285",
  paramount: "31440",
};

function getTvIp() {
  return (localStorage.getItem(TV_IP_KEY) || "").trim();
}

function setTvIp(ip) {
  localStorage.setItem(TV_IP_KEY, ip.trim());
}

function baseUrl(ip) {
  return `http://${ip}:8060`;
}

async function ecpPost(ip, path, timeoutMs = 4000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${baseUrl(ip)}${path}`, {
      method: "POST",
      signal: ctrl.signal,
    });
    return res;
  } finally {
    clearTimeout(t);
  }
}

async function probeTv(ip) {
  try {
    const res = await fetch(`${baseUrl(ip)}/query/device-info`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return null;
    const text = await res.text();
    const name = text.match(/<friendly-device-name>([^<]+)/)?.[1]
      || text.match(/<model-name>([^<]+)/)?.[1]
      || ip;
    return { ip, name };
  } catch {
    return null;
  }
}

async function scanSubnet(prefix) {
  const found = [];
  const batch = 32;
  for (let start = 1; start < 255; start += batch) {
    const jobs = [];
    for (let i = start; i < start + batch && i < 255; i++) {
      const ip = `${prefix}.${i}`;
      jobs.push(
        probeTv(ip).then((r) => {
          if (r) found.push(r);
        }),
      );
    }
    await Promise.all(jobs);
    if (found.length) return found;
  }
  return found;
}

async function guessPrefix() {
  const saved = getTvIp();
  if (saved) return saved.split(".").slice(0, 3).join(".");
  return "192.168.0";
}

async function discover() {
  const saved = getTvIp();
  if (saved) {
    const hit = await probeTv(saved);
    if (hit) return [hit];
  }
  return scanSubnet(await guessPrefix());
}

async function sendKey(ip, key) {
  const rokuKey = KEY_MAP[key] || key;
  const res = await ecpPost(ip, `/keypress/${encodeURIComponent(rokuKey)}`);
  if (res.status === 403) {
    throw new Error("TV blocked remote — enable Control by mobile apps in Settings.");
  }
  if (!res.ok) throw new Error(`Key failed (${res.status})`);
}

async function launchApp(ip, app) {
  const id = APPS[app];
  if (!id) throw new Error(`Unknown app: ${app}`);
  const res = await ecpPost(ip, `/launch/${id}`);
  if (!res.ok) throw new Error(`Launch failed (${res.status})`);
}

async function searchBrowse(ip, title) {
  const q = encodeURIComponent(title);
  const res = await ecpPost(
    ip,
    `/search/browse?title=${q}&provider-id=12,13,31440&launch=false&match-any=true`,
    8000,
  );
  if (!res.ok) throw new Error(`Search failed (${res.status})`);
}

async function playTitle(ip, title) {
  const q = encodeURIComponent(title);
  const res = await ecpPost(
    ip,
    `/search/browse?title=${q}&provider-id=12,13,31440&launch=true&match-any=true`,
    12000,
  );
  if (!res.ok) throw new Error(`Play failed (${res.status})`);
}

function isSecureContextBlocking() {
  return window.isSecureContext && location.protocol === "https:";
}

export {
  getTvIp,
  setTvIp,
  probeTv,
  discover,
  sendKey,
  launchApp,
  searchBrowse,
  playTitle,
  isSecureContextBlocking,
};
