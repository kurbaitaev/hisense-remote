"""Hisense TV Remote — local web server."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import server.env  # noqa: F401 — load .env first

from server.discovery import discover_tvs
from server.discovery import _get_local_ips
from server.roku_client import RokuTvClient, probe_roku
from server.llm import llm_provider
from server.roku_ecp2 import RokuEcp2Error, close_roku_session, get_roku_session
from server.tv_client import VidaaTvClient, probe_vidaa
from server.transcribe import transcribe_audio, transcribe_available
from server.setup_check import check_roku_setup

from server.vision_agent import analyze_tv_photo, vision_act, vision_available
from server.voice_agent import handle_voice_command

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
STATIC_DIR = ROOT / "static"

vidaa_client: VidaaTvClient | None = None
config: dict[str, Any] = {}


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(data: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def get_vidaa() -> VidaaTvClient:
    if vidaa_client is None:
        raise HTTPException(400, "Not connected. Set your TV IP first.")
    return vidaa_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config
    config = load_config()
    yield
    if vidaa_client is not None:
        try:
            vidaa_client.disconnect()
        except Exception:
            pass
    host = config.get("host")
    if host and config.get("platform") == "roku":
        try:
            await close_roku_session(host)
        except Exception:
            pass


app = FastAPI(title="Roku Voice Remote", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ConnectRequest(BaseModel):
    host: str
    platform: str = "auto"
    use_ssl: bool = True


class AuthRequest(BaseModel):
    code: str = Field(min_length=4, max_length=4)


class KeyRequest(BaseModel):
    key: str


class VolumeRequest(BaseModel):
    level: int = Field(ge=0, le=100)


class SourceRequest(BaseModel):
    source_id: str
    source_name: str = ""


class AppRequest(BaseModel):
    app: str


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class VisionGoalRequest(BaseModel):
    goal: str = Field(default="Describe the TV screen.", max_length=400)


class AgentRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=400)


class UiPressRequest(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    intent: str = ""


@app.get("/direct")
async def direct_remote():
    """Phone → TV directly (no server proxy). Use HTTP to avoid mixed-content blocks."""
    return FileResponse(STATIC_DIR / "direct.html")


@app.get("/share")
async def share_page():
    """How to share the friend remote (their TV, not yours)."""
    return FileResponse(STATIC_DIR / "share.html")


@app.get("/find")
async def find_tv_page():
    """No physical remote: SSDP-find TVs on LAN, show QR for phone remote."""
    return FileResponse(STATIC_DIR / "find.html")


@app.get("/api/share")
async def share_info():
    """Info for share tooling — friend mode is phone → their Roku."""
    return {
        "ok": True,
        "mode": "friend",
        "description": "Each friend controls their own TV. Deploy web/ publicly.",
        "friend_app": "/static/friend-remote.html",
        "deploy_path": "web/",
        "docs": "SHARE.md",
        "deploy_command": "npx wrangler pages deploy web --project-name=roku-remote",
    }


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.webmanifest")
async def web_manifest():
    return FileResponse(
        STATIC_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/api/config")
async def get_config():
    host = config.get("host")
    platform = config.get("platform")
    tv_reachable: bool | None = None
    if host and platform == "roku":
        try:
            tv_reachable = await probe_roku(host, timeout=2.0)
        except Exception:
            tv_reachable = False

    local_ips = _get_local_ips()
    return {
        "host": host,
        "platform": platform,
        "use_ssl": config.get("use_ssl", True),
        "connected": tv_reachable is True or vidaa_client is not None,
        "tv_reachable": tv_reachable,
        "local_ips": local_ips,
        "lan_ok": bool(local_ips),
    }


@app.post("/api/detect")
async def detect_tv(req: ConnectRequest):
    host = req.host.strip()
    results: dict[str, bool] = {}

    roku_ok, vidaa_ssl_ok, vidaa_plain_ok = await asyncio.gather(
        probe_roku(host),
        asyncio.to_thread(probe_vidaa, host, use_ssl=True),
        asyncio.to_thread(probe_vidaa, host, use_ssl=False),
    )
    results["roku"] = roku_ok
    results["vidaa_ssl"] = vidaa_ssl_ok
    results["vidaa_plain"] = vidaa_plain_ok

    if req.platform == "roku" and roku_ok:
        platform = "roku"
    elif req.platform == "vidaa" and (vidaa_ssl_ok or vidaa_plain_ok):
        platform = "vidaa"
        req.use_ssl = vidaa_ssl_ok
    elif req.platform == "auto":
        if roku_ok:
            platform = "roku"
        elif vidaa_ssl_ok:
            platform = "vidaa"
            req.use_ssl = True
        elif vidaa_plain_ok:
            platform = "vidaa"
            req.use_ssl = False
        else:
            raise HTTPException(404, f"No Hisense TV found at {host}. Check IP and that TV is on.")
    else:
        raise HTTPException(404, f"TV at {host} not reachable with platform '{req.platform}'.")

    return {
        "host": host,
        "platform": platform,
        "use_ssl": req.use_ssl if platform == "vidaa" else None,
        "results": results,
    }


@app.post("/api/connect")
async def connect_tv(req: ConnectRequest):
    global vidaa_client, config

    detection = await detect_tv(req)
    host = detection["host"]
    platform = detection["platform"]

    if platform == "vidaa":
        if vidaa_client is not None:
            try:
                vidaa_client.disconnect()
            except Exception:
                pass
        client = VidaaTvClient(host, use_ssl=req.use_ssl if detection["use_ssl"] is not None else True)
        try:
            client.connect()
        except Exception as exc:
            raise HTTPException(502, f"MQTT connection failed: {exc}") from exc
        vidaa_client = client

    config.update({
        "host": host,
        "platform": platform,
        "use_ssl": detection.get("use_ssl", True),
    })
    save_config(config)

    info: dict[str, Any] = {"host": host, "platform": platform}
    if platform == "roku":
        roku = RokuTvClient(host)
        device = await roku.get_device_info()
        info["device"] = device
        info["ecp_mode"] = device.get("ecp-setting-mode", "unknown")
        try:
            session = await get_roku_session(host)
            cached_home = config.get("home_channel_id")
            if cached_home:
                session._home_channel_id = cached_home
            home_id = await session.discover_home_channel_id()
            info["keys_enabled"] = True
            info["control_mode"] = "ecp-2"
            if home_id:
                info["home_channel_id"] = home_id
                config["home_channel_id"] = home_id
                save_config(config)
        except RokuEcp2Error:
            info["keys_enabled"] = False
            info["control_mode"] = "http"
    return info


@app.post("/api/auth/start")
async def start_auth():
    if config.get("platform") != "vidaa":
        return {"message": "Roku TVs do not require pairing."}
    client = get_vidaa()
    client.start_authorization()
    return {"message": "Enter the 4-digit code shown on your TV."}


@app.post("/api/auth/verify")
async def verify_auth(req: AuthRequest):
    if config.get("platform") != "vidaa":
        return {"message": "Roku TVs do not require pairing."}
    client = get_vidaa()
    client.send_auth_code(req.code)
    return {"message": "Authorization code sent."}


@app.post("/api/key")
async def send_key(req: KeyRequest):
    host = config.get("host")
    platform = config.get("platform")
    if not host or not platform:
        raise HTTPException(400, "Not connected.")

    if platform == "roku":
        try:
            session = await get_roku_session(host)
            await session.send_key(req.key)
            if session._home_channel_id and config.get("home_channel_id") != session._home_channel_id:
                config["home_channel_id"] = session._home_channel_id
                save_config(config)
        except RokuEcp2Error as exc:
            # Volume keys still work over plain HTTP on TVs with limited ECP.
            if req.key in ("volume_up", "volume_down", "mute"):
                try:
                    roku = RokuTvClient(host)
                    await roku.send_key(req.key)
                except Exception as http_exc:
                    raise HTTPException(502, str(exc)) from http_exc
            else:
                raise HTTPException(502, str(exc)) from exc
    else:
        client = get_vidaa()
        client.send_key(req.key)

    return {"ok": True, "key": req.key}


@app.get("/api/volume")
async def get_volume():
    platform = config.get("platform")
    if platform == "roku":
        return {"note": "Roku volume is typically controlled via TV/AVR, not ECP."}
    client = get_vidaa()
    volume = client.get_volume()
    if volume is None:
        raise HTTPException(504, "No volume response from TV.")
    return volume


@app.post("/api/volume")
async def set_volume(req: VolumeRequest):
    if config.get("platform") != "vidaa":
        raise HTTPException(400, "Volume control only available on VIDAA TVs.")
    client = get_vidaa()
    client.set_volume(req.level)
    return {"level": req.level}


@app.get("/api/sources")
async def get_sources():
    if config.get("platform") != "vidaa":
        raise HTTPException(400, "Source list only available on VIDAA TVs.")
    client = get_vidaa()
    return client.get_sources()


@app.post("/api/source")
async def set_source(req: SourceRequest):
    if config.get("platform") != "vidaa":
        raise HTTPException(400, "Source switching only available on VIDAA TVs.")
    client = get_vidaa()
    client.set_source(req.source_id, req.source_name)
    return {"source_id": req.source_id}


@app.get("/api/state")
async def get_state():
    if config.get("platform") != "vidaa":
        host = config.get("host")
        if not host:
            raise HTTPException(400, "Not connected.")
        roku = RokuTvClient(host)
        return await roku.get_active_app()
    client = get_vidaa()
    state = client.get_tv_state()
    if state is None:
        raise HTTPException(504, "No state response from TV.")
    return state


@app.get("/api/setup")
async def tv_setup_status():
    """Check TV prerequisites for voice control and full automation."""
    host = config.get("host")
    platform = config.get("platform")
    if not host:
        raise HTTPException(400, "Not connected — set your TV IP first.")
    if platform != "roku":
        return {
            "platform": platform,
            "ready_for_voice": platform == "vidaa",
            "note": "Full voice automation is tuned for Roku TVs. VIDAA supports buttons only.",
        }
    return await check_roku_setup(host)


@app.get("/api/agent/status")
async def agent_status():
    from server.llm import llm_available, llm_provider

    return {
        "enabled": True,
        "brain": llm_provider() or "rules",
        "llm": llm_available(),
        "mode": "play",
        "search_behavior": "Roku /search/browse API → deep-link app → play (no keyboard typing)",
        "fast_commands": ["open_app", "send_key", "send_keys", "type_text", "go_home"],
        "hint": "Play/watch uses TMDB + Roku search API — not blind key mashing.",
    }


@app.post("/api/agent/run")
async def agent_run(req: AgentRequest):
    """Legacy route — same search-only handler as /api/voice."""
    host = config.get("host")
    platform = config.get("platform")
    if not host or platform != "roku":
        raise HTTPException(400, "Roku TV not connected.")

    try:
        session = await get_roku_session(host)
        result = await handle_voice_command(session, req.goal.strip())
        return {"ok": True, **result}
    except RokuEcp2Error as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/vision/status")
async def vision_status():
    return {
        "experimental": True,
        "advertised": False,
        "enabled": vision_available(),
        "model": os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
        "mode": "phone_camera",
        "note": "Experimental API — not part of the default voice search flow.",
        "hint": "Requires GEMINI_API_KEY. Point a phone camera at the TV for screen analysis.",
    }


@app.post("/api/vision/see")
async def vision_see(
    image: UploadFile = File(...),
    goal: str = Form(default="Describe the TV screen."),
):
    """Analyze a phone photo of the TV without pressing any keys."""
    host = config.get("host")
    platform = config.get("platform")
    if not host or platform != "roku":
        raise HTTPException(400, "Roku TV not connected.")
    if not vision_available():
        raise HTTPException(400, "GEMINI_API_KEY required for vision.")

    data = await image.read()
    mime = image.content_type or "image/jpeg"

    ecp_context: dict[str, Any] | None = None
    try:
        from server.tv_ui_reader import read_ui

        session = await get_roku_session(host)
        ui = await read_ui(session, include_device=False)
        ecp_context = {
            "app_name": ui.app_name,
            "app_id": ui.app_id,
            "screen": ui.screen.value,
            "summary": ui.summary(),
            "player_state": ui.player.state if ui.player else "none",
        }
    except Exception:
        pass

    try:
        analysis = await analyze_tv_photo(
            data,
            goal=goal,
            ecp_context=ecp_context,
            mime_type=mime,
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc

    return {"ok": True, **analysis}


@app.post("/api/vision/act")
async def vision_act_once(
    image: UploadFile = File(...),
    goal: str = Form(default="Help control the TV toward the user's goal."),
):
    """See the TV via camera photo and press one remote key if confident."""
    host = config.get("host")
    platform = config.get("platform")
    if not host or platform != "roku":
        raise HTTPException(400, "Roku TV not connected.")
    if not vision_available():
        raise HTTPException(400, "GEMINI_API_KEY required for vision.")

    data = await image.read()
    mime = image.content_type or "image/jpeg"

    try:
        session = await get_roku_session(host)
        from server.tv_ui_reader import read_ui

        ui = await read_ui(session, include_device=False)
        ecp_context = {
            "app_name": ui.app_name,
            "app_id": ui.app_id,
            "screen": ui.screen.value,
            "summary": ui.summary(),
            "player_state": ui.player.state if ui.player else "none",
        }
        result = await vision_act(
            session,
            data,
            goal=goal,
            ecp_context=ecp_context,
            mime_type=mime,
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except RokuEcp2Error as exc:
        raise HTTPException(502, str(exc)) from exc

    return {"ok": True, **result}


@app.post("/api/vision/goal")
async def vision_goal_command(req: VisionGoalRequest):
    """Voice/text goal without a new photo — uses ECP context only (limited)."""
    raise HTTPException(
        400,
        "Vision goals require a camera photo. Use the Vision panel: point your phone at the TV, then tap Do one step.",
    )


@app.get("/api/voice/status")
async def voice_status():
    from server.llm import llm_available

    local_ip = _get_local_ip()
    brain = llm_provider() or "rules"
    return {
        "enabled": True,
        "agent": brain,
        "brain": brain,
        "llm": llm_available(),
        "transcribe": transcribe_available(),
        "mic_mode": "groq_whisper" if transcribe_available() else "text",
        "secure_context": True,  # client checks window.isSecureContext
        "mic_requires_https": True,
        "https_url": f"https://{local_ip}:8443" if local_ip else None,
        "mode": "play",
        "search_behavior": "Roku /search/browse → app deep-link → play",
        "hints": [
            "Play Pursuit of Happyness",
            "Watch Inception on Netflix",
            "Open Netflix",
            "Press down",
            "Go home",
        ],
        "user_action_after_search": None,
    }


@app.post("/api/voice/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)):
    if not transcribe_available():
        raise HTTPException(400, "Groq transcription not configured.")

    data = await audio.read()
    if len(data) < 800:
        raise HTTPException(400, "Recording too short. Hold the mic and speak clearly.")
    if len(data) > 24 * 1024 * 1024:
        raise HTTPException(400, "Recording too long (max 25 MB).")

    filename = audio.filename or "voice.webm"
    content_type = audio.content_type or "audio/webm"

    try:
        text = await transcribe_audio(data, filename=filename, content_type=content_type)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc

    return {"ok": True, "text": text}


@app.post("/api/voice/demo")
async def voice_demo(req: VoiceRequest):
    """Search-only debug — types query in Roku Search, does not play."""
    host = config.get("host")
    platform = config.get("platform")
    if not host or not platform:
        raise HTTPException(400, "Not connected.")
    if platform != "roku":
        raise HTTPException(400, "Voice demo supports Roku TVs only.")

    from server.roku_search_only import run_roku_search_only
    from server.voice_agent import parse_command

    try:
        command = await parse_command(req.text.strip())
        title = (command.title or req.text.strip()).strip()
        session = await get_roku_session(host)
        result = await run_roku_search_only(
            session,
            heard=req.text.strip(),
            title=title,
            app=command.app,
        )

        return {
            "ok": True,
            "heard": req.text.strip(),
            "plan": result.plan.to_dict(),
            "search_query": result.search_query,
            "search_method": result.method,
            "search_steps": result.log_text(),
            "screen_context": result.screen_context,
            "note": "Search-only — no playback keys sent.",
        }
    except RokuEcp2Error as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/tv/ui")
async def tv_ui_snapshot():
    """Read full interpreted TV UI state (app, search bar, player, blind spots)."""
    host = config.get("host")
    platform = config.get("platform")
    if not host or platform != "roku":
        raise HTTPException(400, "Roku TV not connected.")

    from server.tv_ui_reader import read_ui

    try:
        session = await get_roku_session(host)
        ui = await read_ui(session, include_device=True)
        return {"ok": True, "ui": ui.to_dict()}
    except RokuEcp2Error as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/tv/ui/atlas")
async def tv_ui_atlas():
    """Signal map: what the TV exposes vs what stays blind."""
    atlas_path = ROOT / "data" / "ui_atlas.json"
    if not atlas_path.exists():
        raise HTTPException(404, "UI atlas not found.")
    return json.loads(atlas_path.read_text())


@app.post("/api/tv/ui/press")
async def tv_ui_press(req: UiPressRequest):
    """Press one key and return before/after UI snapshots with explained delta."""
    host = config.get("host")
    platform = config.get("platform")
    if not host or platform != "roku":
        raise HTTPException(400, "Roku TV not connected.")

    from server.roku_ecp2 import KEY_MAP
    from server.tv_ui_reader import press_and_read

    roku_key = KEY_MAP.get(req.key.lower(), req.key)
    try:
        session = await get_roku_session(host)
        before, after, step = await press_and_read(
            session,
            roku_key,
            intent=req.intent or req.key,
        )
        return {
            "ok": True,
            "key": req.key,
            "roku_key": roku_key,
            "before": before.to_dict(),
            "after": after.to_dict(),
            "delta": step.delta,
            "explain": step.explain(),
        }
    except RokuEcp2Error as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/voice")
async def voice_command(req: VoiceRequest):
    host = config.get("host")
    platform = config.get("platform")
    if not host or not platform:
        raise HTTPException(400, "Not connected.")
    if platform != "roku":
        raise HTTPException(400, "Voice assistant currently supports Roku TVs only.")

    try:
        session = await get_roku_session(host)
        result = await handle_voice_command(session, req.text.strip())
        return {"ok": True, **result}
    except RokuEcp2Error as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/app")
async def launch_app(req: AppRequest):
    host = config.get("host")
    platform = config.get("platform")
    if not host or not platform:
        raise HTTPException(400, "Not connected.")

    app_name = req.app.lower()
    if platform == "roku":
        try:
            session = await get_roku_session(host)
            await session.launch_app(app_name)
        except RokuEcp2Error as exc:
            raise HTTPException(502, str(exc)) from exc
    else:
        client = get_vidaa()
        url_map = {
            "netflix": ("Netflix", "netflix"),
            "youtube": ("YouTube", "youtube"),
            "amazon": ("Amazon", "amazon"),
            "prime": ("Amazon", "amazon"),
        }
        if app_name not in url_map:
            raise HTTPException(400, f"Unknown app: {app_name}")
        name, url = url_map[app_name]
        client.launch_app(name, url)

    return {"app": app_name}


@app.get("/api/health")
async def health_check():
    """Fast liveness check — no network scan."""
    local_ip = _get_local_ip()
    local_ips = _get_local_ips()
    host = config.get("host")
    tv_reachable: bool | None = None
    if host and config.get("platform") == "roku":
        try:
            tv_reachable = await probe_roku(host, timeout=2.0)
        except Exception:
            tv_reachable = False

    issues: list[str] = []
    if not local_ips:
        issues.append(
            "Server has no LAN network access — start with ./start.sh in Terminal.app "
            "(not from a sandboxed IDE shell)."
        )
    if host and tv_reachable is False:
        issues.append(
            f"TV at {host} is not responding on port 8060 — check TV is on, "
            "same Wi‑Fi, and IP in Settings → Network → About."
        )

    return {
        "ok": True,
        "host": host,
        "platform": config.get("platform"),
        "server_ip": local_ip,
        "local_ips": local_ips,
        "lan_ok": bool(local_ips),
        "tv_reachable": tv_reachable,
        "issues": issues,
        "urls": {
            "https": f"https://{local_ip}:8443" if local_ip else None,
            "http": f"http://{local_ip}:8080" if local_ip else None,
        },
    }


@app.get("/api/scan")
async def scan_network(platform: str = "auto"):
    """Discover TVs on Wi-Fi via saved host, mDNS, and subnet scan."""
    from server.discovery import _get_local_ips, _subnet_prefixes, discover_tvs_with_diagnostics

    try:
        result = await discover_tvs_with_diagnostics(platform=platform, timeout=5.0)
    except Exception as exc:
        raise HTTPException(500, f"Scan error: {exc}") from exc

    saved = result.get("saved_host")
    reachable = result.get("saved_host_reachable")
    hint = None
    if not result["tvs"]:
        if saved and reachable is False:
            hint = (
                f"Saved TV at {saved} is not responding. "
                "Check the TV is on, same Wi‑Fi, and get the IP from Settings → Network → About."
            )
        elif not result.get("local_ips"):
            hint = "Server has no LAN IP — run ./start.sh on your Mac (same Wi‑Fi as the TV)."
        else:
            hint = "No Roku found on your network. Enter the TV IP manually."

    return {
        "tvs": result["tvs"],
        "method": "saved+ssdp+mdns+arp+subnet" if platform in ("auto", "roku") else "subnet",
        "local_ips": result.get("local_ips") or _get_local_ips(),
        "scan_subnets": result.get("scan_subnets") or _subnet_prefixes(),
        "saved_host": saved,
        "saved_host_reachable": reachable,
        "hint": hint,
    }


@app.post("/api/connect/auto")
async def auto_connect(platform: str = "roku"):
    """Find a TV on Wi-Fi and connect automatically."""
    tvs = await discover_tvs(platform=platform, timeout=5.0)
    if not tvs:
        raise HTTPException(
            404,
            "No TV found on Wi-Fi. Make sure your TV is on and on the same network.",
        )
    tv = tvs[0]
    req = ConnectRequest(host=tv["ip"], platform=tv["platform"])
    return await connect_tv(req)


def _get_local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None