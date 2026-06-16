# TV Voice Control (Hisense Roku)

Local voice-controlled TV remote for your **43" Hisense Roku TV**. Runs on your Mac, controls the TV over Wi‑Fi, no cloud account required.

**Project path:** `~/hisense-remote`

## What it does

- **Speech control** — hold the mic and say “Play Inception”, “Open Netflix”, “Press down”, “Type batman”, “Go home”
- **Button remote** — d-pad, volume, apps, numpad from phone or laptop browser
- **Smart play** — searches TMDB/Brave, opens the right streaming app, navigates and presses play
- **Developer tools** — sideload channels, scene-graph access when full ECP is enabled

## Quick start

```bash
cd ~/hisense-remote
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add GROQ_API_KEY for speech
./start.sh
```

Open on your phone (same Wi‑Fi):

- **HTTPS (mic works):** `https://<your-mac-ip>:8443`
- **HTTP:** `http://<your-mac-ip>:8080`

The app auto-discovers your Roku TV and reconnects on launch.

## Voice setup (recommended)

1. Copy `.env.example` → `.env`
2. Add a [Groq API key](https://console.groq.com/keys) as `GROQ_API_KEY`
   - Powers **Whisper** transcription (hold-to-talk)
   - Powers **Llama** command parsing (optional but smarter)
3. Open the **HTTPS** URL on your phone and accept the certificate warning once
4. Hold the mic button, speak, release — the TV executes the command

### Example voice commands

| Say this | Action |
|----------|--------|
| Play Inception | Search and play on Netflix/Prime |
| Watch The Matrix on Prime | Open Prime, search, play |
| Open Netflix | Launch app |
| Press down 3 times | Navigate grid |
| Click ok | Select |
| Go back | Back button |
| Type batman | Type into active search field |
| Volume up / Mute | Audio controls |
| Go home | Return to Roku home |

## TV prerequisites (for full control)

Your TV is at **192.168.0.154**. Check status anytime:

```bash
curl -s http://localhost:8080/api/setup | python3 -m json.tool
```

| Setting | Where on TV | Why |
|---------|-------------|-----|
| **Control by mobile apps → Enabled** | Settings → System → Advanced system settings | Required for key presses and voice navigation |
| **Developer mode** | Home×3, Up×2, R,L,R,L,R | Sideload channels, scene graph, debugging |
| **Developer installer** | `http://192.168.0.154` login `rokudev` | Upload channel packages |

> **Important:** ECP is currently `limited` on your TV. For scene-graph reading (`query/sgnodes`) and deepest automation, set **Control by mobile apps** to **Enabled** (not Limited).

## Roku developer channel

Package and install the **TV Voice Bridge** dev channel:

```bash
source .venv/bin/activate
python3 scripts/install_roku_channel.py
# or package only:
bash scripts/package_roku_channel.sh
```

Valid zip layout (top-level `manifest`, not nested in a folder):

```
tv-voice-bridge.zip
├── manifest
├── source/Main.brs
├── components/MainScene.xml
└── images/
```

## Project layout

```
hisense-remote/
├── server/           # FastAPI backend
│   ├── main.py       # HTTP API
│   ├── roku_ecp2.py  # Authenticated TV control (ECP-2)
│   ├── voice_agent.py
│   ├── tv_ui_reader.py
│   └── setup_check.py
├── static/           # Phone/laptop web remote UI
├── roku-channel/     # Sideloaded BrightScript channel
├── scripts/          # TV probes, tests, channel installer
├── data/             # UI capability atlas for this TV model
├── config.json       # Your TV IP (auto-saved, gitignored)
├── .env              # API keys (gitignored)
└── start.sh          # Launch HTTP + HTTPS servers
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/connect` | POST | Connect to TV |
| `/api/key` | POST | Send remote key |
| `/api/voice` | POST | Run voice/text command |
| `/api/voice/transcribe` | POST | Groq Whisper transcription |
| `/api/setup` | GET | Prerequisites checklist |
| `/api/tv/ui` | GET | Current TV UI snapshot |
| `/api/scan` | GET | Discover TVs on Wi‑Fi |

## Optional API keys

| Key | Purpose |
|-----|---------|
| `GROQ_API_KEY` | Speech-to-text + command parsing |
| `GEMINI_API_KEY` | Fallback command parsing + movie lookup |
| `TMDB_API_KEY` | Streaming availability |
| `BRAVE_API_KEY` | Web search for where to watch |

## Troubleshooting

- **Mic doesn't work** — use HTTPS URL, not HTTP
- **Keys rejected** — enable Control by mobile apps on the TV
- **Install failure: application file is empty** — upload a valid `.zip` with `manifest` at the top level
- **Voice play takes 20–40s** — normal; the agent opens apps and navigates visually

## How it works

Roku TVs expose the [External Control Protocol](https://developer.roku.com/docs/developer-program/dev-tools/external-control-api.md) on port **8060**. This project uses **ECP-2** (WebSocket + auth), the same path as the official Roku mobile app, to send keys and read limited UI state (active app, search bar text, player state).

Developer mode unlocks sideloading and `query/sgnodes` for reading on-screen focus and menus.