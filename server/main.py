"""Hisense TV Remote — local web server."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import server.env  # noqa: F401 — load .env first

from server.discovery import discover_tvs
from server.roku_client import RokuTvClient, probe_roku
from server.brave_search import brave_available
from server.llm import llm_provider
from server.roku_ecp2 import RokuEcp2Error, close_roku_session, get_roku_session
from server.tv_client import VidaaTvClient, probe_vidaa
from server.transcribe import transcribe_audio, transcribe_available
from server.setup_check import check_roku_setup
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


app = FastAPI(title="Hisense Remote", lifespan=lifespan)
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


class UiPressRequest(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    intent: str = ""


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def get_config():
    return {
        "host": config.get("host"),
        "platform": config.get("platform"),
        "use_ssl": config.get("use_ssl", True),
        "connected": vidaa_client is not None or bool(config.get("host")),
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


@app.get("/api/voice/status")
async def voice_status():
    local_ip = _get_local_ip()
    return {
        "enabled": True,
        "agent": llm_provider() or "rules",
        "transcribe": transcribe_available(),
        "mic_mode": "groq_whisper" if transcribe_available() else "browser",
        "secure_context": True,  # client checks window.isSecureContext
        "mic_requires_https": True,
        "https_url": f"https://{local_ip}:8443" if local_ip else None,
        "movie_lookup": (
            "tmdb+brave" if os.getenv("TMDB_API_KEY") and brave_available()
            else "brave" if brave_available()
            else "tmdb" if os.getenv("TMDB_API_KEY")
            else "gemini"
        ),
        "hints": [
            "Play Inception",
            "Open Netflix",
            "Press down 3 times",
            "Type batman",
            "Go home",
            "Volume up",
        ],
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
    """Run a voice play command and return step-by-step search debug info."""
    host = config.get("host")
    platform = config.get("platform")
    if not host or not platform:
        raise HTTPException(400, "Not connected.")
    if platform != "roku":
        raise HTTPException(400, "Voice demo supports Roku TVs only.")

    from server.movie_lookup import lookup_media
    from server.play_orchestrator import build_play_plan
    from server.voice_agent import parse_command

    try:
        command = await parse_command(req.text.strip())
        title = (command.title or req.text.strip()).strip()
        media = await lookup_media(title) if title else None
        plan = build_play_plan(
            heard=req.text.strip(),
            requested_title=title,
            requested_app=command.app,
            media=media,
        )

        session = await get_roku_session(host)
        search_result = await session.roku_search_and_play(
            plan.search_text,
            preferred_app=plan.app,
            title=plan.title,
            plan_summary=plan.summary(),
        )

        return {
            "ok": True,
            "heard": req.text.strip(),
            "plan": plan.to_dict(),
            "search_query": search_result.get("query", plan.search_text),
            "search_method": search_result.get("method"),
            "search_steps": search_result.get("steps"),
            "screen_context": search_result.get("screen_context"),
            "screen_trail": search_result.get("screen_trail"),
            "note": (
                "Screen state is polled via ECP-2 (textedit-state, active-app). "
                f"Target query: {search_result.get('query', plan.search_text)!r}"
            ),
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


@app.get("/api/scan")
async def scan_network(platform: str = "auto"):
    """Discover TVs on Wi-Fi via mDNS (Roku) or subnet scan (VIDAA)."""
    tvs = await discover_tvs(platform=platform)
    return {"tvs": tvs, "method": "mdns" if platform in ("auto", "roku") else "subnet"}


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