# Hisense / Roku Remote

**For friends:** each person controls **their own TV** on **their Wi‑Fi**.  
Share one free web link — see **[SHARE.md](./SHARE.md)**. No your Mac, no your TV.

**Optional for you:** voice AI + always-on bridge on a Mac/Pi for a richer experience on *your* network.

---

## Friend mode (share this)

```
Friend's phone ──Wi‑Fi──► Friend's Roku
```

1. Deploy `web/` once (Cloudflare Pages / GitHub Pages)  
2. Send them the URL  
3. They open it, connect to *their* TV, use the remote  

Details: **[SHARE.md](./SHARE.md)** · `./scripts/share.sh`

---

## Dev / voice mode (optional)

Voice-controlled remote for **Hisense Roku TVs**. Runs as a bridge on your home network (Pi, NAS, or Mac).

## Features

- **Play by voice** — “Play Pursuit of Happyness” → TMDB lookup → Roku `/search/browse` API → opens the app and plays (no on-screen keyboard typing)
- **Button remote** — d-pad, volume, apps from any phone browser
- **Auto-discovery** — finds your Roku on Wi‑Fi

## Why search stopped typing garbage

Blind `Lit_` keypresses hit the **on-screen keyboard** when focus isn’t in the search bar → random letters.

**Fix:** use Roku’s HTTP API first:

```
POST http://<tv-ip>:8060/search/browse?title=The+Pursuit+of+Happyness&provider-id=12,13&launch=true
```

That opens Search with the title already filled — zero keyboard keys. Fallback is ECP-2 `send_text` only when the TV reports focus **in** the search field.

## Quick start (Mac / dev)

```bash
git clone <repo> hisense-remote && cd hisense-remote
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # GROQ_API_KEY for mic
cp config.example.json config.json   # set "host" to TV IP
./start.sh
```

Phone (same Wi‑Fi): `https://<computer-ip>:8443`

## Direct mode — no App Store, no always-on server

App Store Roku remotes talk **phone → TV** on port 8060. You can do the same without publishing an app:

1. On your phone (same Wi‑Fi), open **`http://<any-device-on-lan>:8080/direct`** — use HTTP, not HTTPS (Safari blocks HTTPS pages from calling the TV).
2. Enter TV IP (or tap **Find** to scan the subnet).
3. **Share → Add to Home Screen** — installs like an app.
4. After the first visit, the page is cached. **Your Mac can be off** — buttons and “Play …” go straight to `192.168.x.x:8060`.

| Mode | Server needed? | Voice mic? | Works like App Store remote? |
|------|----------------|------------|------------------------------|
| **Direct** (`/direct` over HTTP) | No (after one-time install) | No | Yes — d-pad, apps, search/play |
| **Full** (`:8443` HTTPS) | Yes (Mac/Pi 24/7) | Yes (Groq) | No — phone → server → TV |

**No Mac even for setup?** Ask any device on Wi‑Fi to serve the folder once (`python3 -m http.server 8080` in the project), open `/direct`, add to home screen. Or sideload a [Capacitor](https://capacitorjs.com) build via SideStore/AltStore (Apple dev account, not App Store).

## Always-on deploy (recommended — not your laptop)

The TV is on your LAN. The bridge must live **on the same network** 24/7 — a Pi or NAS, not a cloud VPS.

### Docker on Raspberry Pi / home server

```bash
sudo apt install docker.io docker-compose-plugin
git clone <repo> /opt/hisense-remote && cd /opt/hisense-remote

# One-time: TV IP + installed apps
sudo mkdir -p /var/lib/hisense-remote
sudo cp config.example.json /var/lib/hisense-remote/config.json
sudo nano /var/lib/hisense-remote/config.json   # host: 192.168.x.x
sudo cp .env.example /var/lib/hisense-remote/.env

# Edit docker-compose.yml volume to /var/lib/hisense-remote if preferred
docker compose up -d --build
```

Open `https://<pi-ip>:8443` from your phone.

### Boot on power-up (systemd)

```bash
sudo cp deploy/hisense-remote.service /etc/systemd/system/
sudo systemctl enable --now hisense-remote
```

### Remote access from anywhere (optional)

Cloud VPS **cannot** reach your TV. Use **Tailscale** on the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg --https=443 http://127.0.0.1:8443
```

Then open `https://<pi-tailscale-name>.ts.net` on your phone (mic works over Tailscale HTTPS).

## Configuration

`config.json`:

| Field | Purpose |
|-------|---------|
| `host` | Roku TV IP (Settings → Network → About) |
| `installed_apps` | Apps on your TV: `netflix`, `prime`, `paramount`, … |
| `home_channel_id` | Auto-filled on first connect |
| `paramount.profile_down_presses` | `0` = OK top profile (adult); `1` = Down once if Kids is on top |

## TV setup (required once)

**Settings → System → Advanced system settings → Control by mobile apps → Enabled**

## Example commands

| Say or type | What happens |
|-------------|--------------|
| `Play Pursuit of Happyness` | TMDB → search/browse → play on Netflix/Prime/etc. |
| `Watch Inception on Netflix` | Deep-link Netflix search → OK top result |
| `Open Netflix` | Launch app |
| `Press down 3 times` | Down × 3 |
| `Go home` | Roku home |

## API

| Endpoint | Description |
|----------|-------------|
| `POST /api/voice` | Voice/text — play or remote keys |
| `POST /api/voice/demo` | Search-only debug (no play keys) |
| `GET /api/tv/ui` | Live TV state (search bar text, player, focus) |
| `GET /api/health` | Server liveness |

## Optional keys

| Key | Purpose |
|-----|---------|
| `GROQ_API_KEY` | Mic + smarter parsing |
| `TMDB_API_KEY` | Correct movie titles for search |
| `GEMINI_API_KEY` | Fallback parser / agent loop |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Random letters in search | Update to latest — uses `/search/browse`, not keyboard |
| Keys rejected | Enable *Control by mobile apps* on TV |
| Mic dead | Use HTTPS (`:8443`) — or use Direct mode for buttons only |
| HTTPS page can't control TV | Use **Direct mode** at `http://…:8080/direct` |
| Server dies when Mac sleeps | Run Docker on Pi with `restart: unless-stopped` |
| Away from home | Tailscale serve on the Pi (not cloud deploy) |

## License

MIT — see [LICENSE](LICENSE).
