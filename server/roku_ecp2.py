"""Roku ECP-2 WebSocket client — same protocol as the official Roku mobile app."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from server.tv_screen import ScreenContext, read_screen
from server.tv_ui_reader import ReadContext
import websockets
from websockets.asyncio.client import connect

logger = logging.getLogger(__name__)

ROKU_AUTH_KEY_SEED = "95E610D0-7C29-44EF-FB0F-97F1FCE4C297"

KEY_MAP = {
    "power": "PowerOff",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "ok": "Select",
    "back": "Back",
    "menu": "Info",
    "exit": "Back",
    "home": "Home",
    "volume_up": "VolumeUp",
    "volume_down": "VolumeDown",
    "mute": "VolumeMute",
    "channel_up": "ChannelUp",
    "channel_down": "ChannelDown",
    "play": "Play",
    "pause": "Pause",
    "stop": "Back",
    "rewind": "Rev",
    "fast_forward": "Fwd",
    "search": "Search",
    "0": "Lit_0",
    "1": "Lit_1",
    "2": "Lit_2",
    "3": "Lit_3",
    "4": "Lit_4",
    "5": "Lit_5",
    "6": "Lit_6",
    "7": "Lit_7",
    "8": "Lit_8",
    "9": "Lit_9",
}

APP_MAP = {
    "netflix": "12",
    "youtube": "837",
    "amazon": "13",
    "prime": "13",
    "paramount": "31440",
    "disney": "291097",
    "hulu": "2285",
}


class RokuEcp2Error(Exception):
    pass


def _char_transform(char: int, offset: int) -> int:
    if ord("0") <= char <= ord("9"):
        digit = char - ord("0")
    elif ord("A") <= char <= ord("F"):
        digit = char - ord("A") + 10
    else:
        return char
    value = (15 - digit + offset) & 15
    if value < 10:
        return value + ord("0")
    return value + ord("A") - 10


def _auth_key_material() -> bytes:
    return bytes(_char_transform(ord(c), 9) for c in ROKU_AUTH_KEY_SEED)


def _auth_response(challenge: str) -> str:
    digest = hashlib.sha1(challenge.encode() + _auth_key_material()).digest()
    return base64.b64encode(digest).decode()


def _parse_ecp_xml(content_data: str | None) -> dict[str, str]:
    if not content_data:
        return {}
    try:
        root = ET.fromstring(base64.b64decode(content_data))
    except (ET.ParseError, ValueError):
        return {}
    if root.tag == "active-app":
        app = root.find("app")
        if app is None:
            return {}
        return {
            "id": app.get("id", ""),
            "type": app.get("type", ""),
            "name": (app.text or "").strip(),
        }
    return {}


class RokuEcp2Client:
    """Authenticated WebSocket session to a Roku TV."""

    def __init__(self, host: str, timeout: float = 8.0):
        self.host = host
        self.timeout = timeout
        self._ws: Any = None
        self._request_id = 2
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task | None = None
        self._auth_challenge = asyncio.Event()
        self._auth_done = asyncio.Event()
        self._auth_ok = False
        self._challenge: str | None = None
        self._connected = False
        self._last_activity = 0.0
        self._home_channel_id: str | None = None

    @property
    def connected(self) -> bool:
        return self._connected and self._ws is not None

    def _handle_message(self, msg: dict[str, Any]) -> None:
        if msg.get("notify") == "authenticate" and "param-challenge" in msg:
            self._challenge = msg["param-challenge"]
            self._auth_challenge.set()
            return

        if msg.get("response") == "authenticate":
            self._auth_ok = msg.get("status") == "200"
            self._auth_done.set()
            return

        response_id = msg.get("response-id")
        if response_id and response_id in self._pending:
            future = self._pending.pop(response_id)
            if not future.done():
                future.set_result(msg)

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                self._handle_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("ECP-2 reader stopped: %s", exc)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RokuEcp2Error(str(exc)))
            self._pending.clear()
            self._connected = False

    async def connect(self) -> None:
        if self.connected:
            return
        await self.disconnect()

        self._auth_challenge.clear()
        self._auth_done.clear()
        self._auth_ok = False
        self._challenge = None

        uri = f"ws://{self.host}:8060/ecp-session"
        self._ws = await connect(
            uri,
            subprotocols=[websockets.Subprotocol("ecp-2")],
            additional_headers={"Origin": "iOS"},
            open_timeout=self.timeout,
            ping_interval=20,
            ping_timeout=20,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        try:
            await asyncio.wait_for(self._auth_challenge.wait(), timeout=self.timeout)
        except TimeoutError as exc:
            raise RokuEcp2Error("TV did not send authentication challenge") from exc

        auth_msg = {
            "request": "authenticate",
            "request-id": "1",
            "param-response": _auth_response(self._challenge or ""),
            "param-has-microphone": "false",
            "param-microphone-sample-rates": "1600",
            "param-client-friendly-name": "Hisense Remote",
        }
        await self._ws.send(json.dumps(auth_msg))

        try:
            await asyncio.wait_for(self._auth_done.wait(), timeout=self.timeout)
        except TimeoutError as exc:
            raise RokuEcp2Error("Authentication timed out") from exc

        if not self._auth_ok:
            raise RokuEcp2Error("Authentication rejected by TV")

        self._connected = True
        self._last_activity = time.monotonic()

    async def disconnect(self) -> None:
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RokuEcp2Error("Disconnected"))
        self._pending.clear()

    async def _ensure_connected(self) -> None:
        if not self.connected:
            await self.connect()

    async def _refresh_if_stale(self, max_idle: float = 25.0) -> None:
        if self.connected and (time.monotonic() - self._last_activity) > max_idle:
            await self.connect()

    async def query_active_app(self) -> dict[str, str]:
        response = await self._send_request({"request": "query-active-app"})
        return _parse_ecp_xml(response.get("content-data") if response else None)

    async def discover_home_channel_id(self) -> str | None:
        if self._home_channel_id:
            return self._home_channel_id
        app = await self.query_active_app()
        if app.get("type") == "home" and app.get("id"):
            self._home_channel_id = app["id"]
        return self._home_channel_id

    async def _launch_channel(self, channel_id: str) -> None:
        await self._send_request({"request": "launch", "param-channel-id": channel_id})

    async def _send_request(
        self,
        payload: dict[str, Any],
        *,
        key_timeout: float | None = None,
        require_response: bool = True,
    ) -> dict[str, Any] | None:
        await self._ensure_connected()

        async with self._lock:
            req_id = str(self._request_id)
            self._request_id += 1
            payload = {**payload, "request-id": req_id}

            future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending[req_id] = future

            try:
                assert self._ws is not None
                await self._ws.send(json.dumps(payload))
                wait_for = key_timeout if key_timeout is not None else self.timeout
                if not require_response:
                    self._pending.pop(req_id, None)
                    self._last_activity = time.monotonic()
                    return None
                response = await asyncio.wait_for(future, timeout=wait_for)
            except TimeoutError:
                self._pending.pop(req_id, None)
                if payload.get("request") == "key-press":
                    # Key was likely delivered even if TV didn't ACK in time
                    self._last_activity = time.monotonic()
                    return None
                self._connected = False
                raise RokuEcp2Error("TV did not respond in time")
            except Exception:
                self._pending.pop(req_id, None)
                self._connected = False
                raise

            status = str(response.get("status", ""))
            if status and status not in ("200", "204"):
                raise RokuEcp2Error(response.get("status-msg") or f"TV returned status {status}")
            self._last_activity = time.monotonic()
            return response

    async def _send_key_raw(self, roku_key: str) -> None:
        await self._send_request(
            {"request": "key-press", "param-key": roku_key},
            key_timeout=2.5,
        )

    async def send_key(self, key: str) -> None:
        if key == "home":
            await self.go_home()
            return

        roku_key = KEY_MAP.get(key, key)
        for attempt in range(2):
            try:
                await self._refresh_if_stale()
                await self._send_key_raw(roku_key)
                return
            except RokuEcp2Error:
                if attempt == 0:
                    await self.connect()
                    continue
                raise

    async def go_home(self) -> None:
        """Return to the Roku home screen (launch, same path as app buttons)."""
        for attempt in range(2):
            try:
                await self._refresh_if_stale()

                home_id = self._home_channel_id or await self.discover_home_channel_id()
                if home_id:
                    await self._launch_channel(home_id)
                    await asyncio.sleep(0.2)
                    app = await self.query_active_app()
                    if app.get("type") == "home":
                        self._home_channel_id = app.get("id") or home_id
                        return

                await self._send_key_raw("Home")
                await asyncio.sleep(0.25)
                app = await self.query_active_app()
                if app.get("type") == "home" and app.get("id"):
                    self._home_channel_id = app["id"]
                    return

                await self._send_key_raw("Home")
                return
            except RokuEcp2Error:
                if attempt == 0:
                    for _ in range(3):
                        try:
                            await self._send_key_raw("Back")
                            await asyncio.sleep(0.1)
                        except RokuEcp2Error:
                            break
                    await self.connect()
                    continue
                raise

    async def launch_app(self, app_name: str) -> None:
        app_id = APP_MAP.get(app_name.lower())
        if not app_id:
            raise RokuEcp2Error(f"Unknown app: {app_name}")
        for attempt in range(2):
            try:
                await self._refresh_if_stale()
                await self._launch_channel(app_id)
                return
            except RokuEcp2Error:
                if attempt == 0:
                    await self.connect()
                    continue
                raise

    async def send_text(self, text: str) -> None:
        await self._send_request({"request": "input", "param-text": text})

    @staticmethod
    def _sanitize_search_query(query: str) -> str:
        """Keep only characters safe for Roku search (letters, digits, spaces)."""
        cleaned = re.sub(r"[^A-Za-z0-9 ]+", "", query)
        return re.sub(r"\s+", " ", cleaned).strip()

    async def _type_lit(self, text: str, *, delay: float = 0.22) -> None:
        """Type into the search field (cursor must already be in the text box)."""
        for ch in text:
            if ch == " ":
                key = "Lit_ "
            elif ch.isdigit():
                key = f"Lit_{ch}"
            elif ch.isalpha():
                key = f"Lit_{ch.lower()}"
            else:
                continue
            await self._send_key_raw(key)
            await asyncio.sleep(delay)

    async def _release_keys(self, *roku_keys: str) -> None:
        """Best-effort key-up so nothing stays held (avoids gggg repeat typing)."""
        for roku_key in roku_keys:
            try:
                await self._send_request(
                    {"request": "key-up", "param-key": roku_key},
                    require_response=False,
                )
            except RokuEcp2Error:
                pass

    async def _tap_key(self, roku_key: str, *, count: int = 1, delay: float = 0.12) -> None:
        for _ in range(count):
            await self._send_key_raw(roku_key)
            await asyncio.sleep(delay)

    async def _reset_to_home_focus(self) -> None:
        """Return to the main Home row (not a content row like Sports)."""
        for _ in range(4):
            await self._send_key_raw("Back")
            await asyncio.sleep(0.25)
        for _ in range(3):
            await self._send_key_raw("Home")
            await asyncio.sleep(1.0)
            app = await self.query_active_app()
            if (app.get("name") or "").lower() == "home":
                return
        home_id = await self._resolve_home_channel_id()
        if home_id:
            await self._launch_channel(home_id)
            await asyncio.sleep(1.2)

    async def _exit_to_home(self) -> None:
        """Leave search/apps and return to a clean home screen."""
        await self._reset_to_home_focus()

    async def _wipe_search_bar(self) -> None:
        """Clear the search field only when ECP confirms cursor is in the bar."""
        ctx = await read_screen(self)
        if not ctx.in_search_field:
            logger.info("Skip Backspace wipe — focus not in search field")
            return
        await self._tap_key("Backspace", count=40, delay=0.1)
        await self._release_keys("Backspace")
        await asyncio.sleep(0.3)

    async def _open_search_via_api(self, query: str) -> bool:
        """Open Roku universal search with a title — no on-screen keyboard."""
        from server.roku_search_browse import http_search_browse, provider_ids_for_apps

        ids = provider_ids_for_apps()
        if not ids:
            return False
        return await http_search_browse(
            self.host,
            query,
            provider_ids=ids,
            launch=False,
        )

    async def _wait_for_search_text(
        self,
        query: str,
        *,
        timeout_s: float = 12.0,
    ) -> ScreenContext:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ctx = await read_screen(self, target_query=query)
            if ctx.search_matches(query):
                return ctx
            if ctx.on_search() and ctx.search_text:
                return ctx
            await asyncio.sleep(0.5)
        return await read_screen(self, target_query=query)

    async def _type_in_search(self, query: str) -> str:
        """Fill the Roku search bar without Lit_ keys (they type garbage on the keyboard)."""
        query = self._sanitize_search_query(query)
        if not query:
            raise RokuEcp2Error("Empty search query")

        logger.info("Roku search: %r", query)

        if await self._open_search_via_api(query):
            ctx = await self._wait_for_search_text(query)
            if ctx.search_matches(query):
                return "search-browse"

        ctx = await read_screen(self, target_query=query)
        if ctx.search_matches(query):
            return "search-browse"

        if not ctx.on_search():
            ctx = await self._open_search_minimal([], query)

        ctx = await read_screen(self, target_query=query)
        if ctx.search_matches(query):
            return "already-typed"

        if not ctx.in_search_field:
            try:
                await self.send_text(query)
                await asyncio.sleep(1.0)
                ctx = await read_screen(self, target_query=query)
                if ctx.search_matches(query):
                    return "send-text"
            except RokuEcp2Error:
                pass
            raise RokuEcp2Error(
                "Search field not focused — refusing keyboard keys (would type garbage)",
            )

        if ctx.search_text and not ctx.search_matches(query):
            await self._wipe_search_bar()

        await self.send_text(query)
        await asyncio.sleep(0.8)
        ctx = await read_screen(self, target_query=query)
        if ctx.search_matches(query):
            return "send-text"

        raise RokuEcp2Error(
            f'Search bar shows "{ctx.search_text}" instead of "{query}"',
        )

    async def _open_search_minimal(self, log: list[str], query: str) -> ScreenContext:
        """Open Roku Search — API first, then home navigation."""
        ctx = await read_screen(self, target_query=query)
        if ctx.on_search():
            await self._record_screen_step(log, "Already on Search", ctx)
            return ctx

        if await self._open_search_via_api(query):
            ctx = await self._wait_for_search_text(query, timeout_s=10.0)
            if ctx.on_search():
                await self._record_screen_step(log, "Opened Search via /search/browse", ctx)
                return ctx

        async def try_open_from_home() -> ScreenContext | None:
            sequences = (
                ["Up", "Up", "Right", "Select"],
                ["Up", "Right", "Right", "Select"],
            )
            for sequence in sequences:
                for key in sequence:
                    await self._send_key_raw(key)
                    await asyncio.sleep(0.55)
                await asyncio.sleep(0.8)
                screen = await read_screen(self, target_query=query)
                if screen.on_search():
                    await self._record_screen_step(log, "Opened Search from Home", screen)
                    return screen
            return None

        ctx = await read_screen(self, target_query=query)
        if ctx.phase == "ON_HOME" or ctx.app_name.lower() == "home":
            opened = await try_open_from_home()
            if opened:
                return opened

        home_id = await self._resolve_home_channel_id()
        if home_id:
            await self._launch_channel(home_id)
            await asyncio.sleep(1.0)
        await self._send_key_raw("Home")
        await asyncio.sleep(0.6)
        await self._send_key_raw("Home")
        await asyncio.sleep(0.8)

        opened = await try_open_from_home()
        if opened:
            return opened

        ctx = await read_screen(self, target_query=query)
        await self._record_screen_step(log, "Could not open Search", ctx)
        raise RokuEcp2Error("Could not open Roku Search on this TV")

    async def _press_roku_keys(self, keys: list[str], *, delay: float = 0.5) -> None:
        for key in keys:
            mapped = KEY_MAP.get(key.lower(), key)
            await self._send_key_raw(mapped)
            await asyncio.sleep(delay)

    async def _launch_with_keyword(self, channel_id: str, query: str) -> None:
        """Launch a channel with a search keyword."""
        await self._refresh_if_stale()
        await self._send_request(
            {
                "request": "launch",
                "param-channel-id": channel_id,
                "param-keyword": query,
            },
        )

    async def _http_launch_search(self, channel_id: str, query: str, param: str) -> bool:
        """HTTP deep-link launch (works on TVs with limited ECP)."""
        path = f"/launch/{channel_id}?{param}={quote(query)}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"http://{self.host}:8060{path}")
            return resp.status_code < 400
        except httpx.HTTPError:
            return False

    async def _ecp2_launch_search(
        self,
        channel_id: str,
        query: str,
        *,
        params: tuple[str, ...] = ("search", "keyword", "query"),
    ) -> bool:
        """Try ECP-2 launch with common search parameter names."""
        await self._refresh_if_stale()
        for param in params:
            try:
                await self._send_request(
                    {
                        "request": "launch",
                        "param-channel-id": channel_id,
                        f"param-{param}": query,
                    },
                )
                return True
            except RokuEcp2Error:
                continue
        return False

    async def search_browse(
        self,
        title: str,
        *,
        app_keys: list[str] | None = None,
        launch: bool = True,
    ) -> bool:
        """One-shot search+launch via /search/browse (RokuAlexaLambdaSkill pattern)."""
        from server.roku_search_browse import http_search_browse, provider_ids_for_apps

        ids = provider_ids_for_apps(app_keys)
        return await http_search_browse(
            self.host,
            title,
            provider_ids=ids,
            launch=launch,
            match_any=True,
        )

    async def _deep_link_search(self, app_key: str, query: str) -> bool:
        """Launch a specific app with a search term (best for netflix/paramount/etc.)."""
        app_id = APP_MAP.get(app_key)
        if not app_id:
            return False

        param = {
            "youtube": "search",
            "netflix": "search",
            "prime": "search",
            "amazon": "search",
            "paramount": "search",
            "disney": "search",
            "hulu": "search",
        }.get(app_key, "search")

        if await self._http_launch_search(app_id, query, param):
            return True
        return await self._ecp2_launch_search(app_id, query, params=(param, "keyword", "query"))

    async def _resolve_home_channel_id(self) -> str | None:
        if self._home_channel_id:
            return self._home_channel_id
        return await self.discover_home_channel_id()

    async def type_query(self, query: str) -> None:
        await self.send_text(query)

    async def launch_and_search(
        self,
        app_name: str,
        query: str,
        *,
        content_id: str | None = None,
    ) -> None:
        """Open an app, navigate to search, and type the query."""
        app_key = app_name.lower()
        app_id = APP_MAP.get(app_key)
        if not app_id:
            raise RokuEcp2Error(f"Unknown app: {app_name}")

        if content_id:
            try:
                await self._send_request(
                    {
                        "request": "launch",
                        "param-channel-id": app_id,
                        "param-content-id": content_id,
                    },
                )
                return
            except RokuEcp2Error:
                pass

        # Deep-link search opens the in-app search UI directly on this TV.
        if await self._deep_link_search(app_key, query):
            return

        await self.launch_app(app_key)
        load_wait = {
            "netflix": 4.0,
            "youtube": 3.5,
            "prime": 4.0,
            "amazon": 4.0,
            "paramount": 4.0,
            "disney": 4.0,
            "hulu": 4.0,
        }.get(app_key, 3.5)
        await asyncio.sleep(load_wait)

        search_nav: dict[str, list[str]] = {
            "netflix": ["Up", "Select"],
            "youtube": ["Search"],
            "prime": ["Search"],
            "amazon": ["Search"],
            "paramount": ["Search"],
            "disney": ["Search"],
            "hulu": ["Search"],
        }
        await self._press_roku_keys(search_nav.get(app_key, ["Search"]), delay=0.55)
        await asyncio.sleep(0.7)
        await self.type_query(query)

    async def _screen_state(self) -> str:
        app = await self.query_active_app()
        name = app.get("name") or "Unknown"
        app_id = app.get("id") or "?"
        return f"{name} (id {app_id})"

    async def _record_screen_step(
        self,
        log: list[str],
        action: str,
        ctx: ScreenContext,
    ) -> None:
        log.append(f"• {action}")
        log.append(f"  {ctx.summary()}")
        if ctx.ui:
            if ctx.ui.focus.detail:
                log.append(f"  focus: {ctx.ui.focus.detail}")
            if ctx.ui.blind_spots:
                log.append(f"  blind: {', '.join(ctx.ui.blind_spots[:4])}")

    async def _ensure_search_text(self, query: str, log: list[str]) -> str:
        ctx = await read_screen(self, target_query=query)
        if ctx.search_matches(query):
            await self._record_screen_step(
                log, f'Bar already "{query}" — skip typing', ctx,
            )
            return "skip"

        method = await self._type_in_search(query)
        for _ in range(25):
            await asyncio.sleep(0.25)
            ctx = await read_screen(self, target_query=query)
            if ctx.search_matches(query):
                await self._record_screen_step(
                    log, f'Typed "{query}" via {method}', ctx,
                )
                return method

        ctx = await read_screen(self, target_query=query)
        await self._record_screen_step(
            log, f'Typed "{query}" via {method} (poll timeout)', ctx,
        )
        return method

    def _normalize_preferred_app(self, preferred_app: str | None) -> str | None:
        if not preferred_app:
            return None
        key = preferred_app.strip().lower()
        if key in ("amazon", "prime", "prime video"):
            return "prime"
        if key in ("paramount+", "paramount plus"):
            return "paramount"
        return key if key in APP_MAP else None

    def _preferred_app_id(self, preferred_app: str | None) -> str | None:
        key = self._normalize_preferred_app(preferred_app)
        return APP_MAP.get(key) if key else None

    async def _select_paramount_profile(
        self,
        log: list[str],
        query: str,
        ui_ctx: ReadContext,
    ) -> None:
        """Dismiss Paramount+ profile picker before search/play keys.

        Profiles are vertical: top = adult, below = Kids. Down moves to Kids.
        profile_down_presses in config.json:
        0 = OK on the top highlighted profile (adult);
        1+ = Down that many times before OK (only if adult is not on top).
        """
        from server.apps_config import get_paramount_profile_down_presses

        downs = get_paramount_profile_down_presses()
        await asyncio.sleep(2.0)
        ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
        await self._record_screen_step(
            log,
            "Paramount: Who's Watching — OK on top profile (adult), never Down to Kids",
            ctx,
        )
        for _ in range(downs):
            await self._send_key_raw("Down")
            await asyncio.sleep(0.65)
        await self._send_key_raw("Select")
        await asyncio.sleep(3.0)
        ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
        await self._record_screen_step(
            log,
            f"Paramount: entered profile (Down×{downs}, then OK)",
            ctx,
        )

    async def _wait_for_streaming_app(
        self,
        log: list[str],
        query: str,
        want_id: str,
        ui_ctx: ReadContext,
        *,
        settle_s: float = 6.0,
    ) -> ScreenContext:
        """Wait until deep link lands in the target app and UI settles."""
        deadline = time.monotonic() + 18.0
        while time.monotonic() < deadline:
            ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
            if ctx.app_id == want_id:
                await asyncio.sleep(settle_s)
                ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
                await self._record_screen_step(log, "App ready — search loaded", ctx)
                return ctx
            await asyncio.sleep(0.6)
        ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
        raise RokuEcp2Error(
            f"Timed out waiting for app {want_id} (on {ctx.app_name} id {ctx.app_id})",
        )

    async def _run_streaming_play_keys(
        self,
        log: list[str],
        query: str,
        app_key: str,
        title: str,
        ui_ctx: ReadContext,
    ) -> bool:
        if app_key == "paramount":
            ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
            if ctx.on_paramount() and ctx.phase == "ON_PARAMOUNT" and not ctx.is_playing():
                await self._send_key_raw("Search")
                await asyncio.sleep(2.5)
                ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
                await self._record_screen_step(log, "Opened Paramount in-app search", ctx)
                await self.send_text(query)
                await asyncio.sleep(4.5)
                ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
                await self._record_screen_step(log, f'Typed "{query}" in Paramount search', ctx)
                await self._send_key_raw("Down")
                await asyncio.sleep(0.8)
                ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
                await self._record_screen_step(log, "Down — focus search results row", ctx)
            else:
                await asyncio.sleep(2.0)
                await self._leave_search_field(log, query)

        await self._safe_select(log, query, f'OK — "{title}"')
        await asyncio.sleep(2.5)
        ctx = await read_screen(self, target_query=query, ctx=ui_ctx)

        if app_key == "netflix":
            if ctx.player_state == "pause":
                await self._record_screen_step(log, "Resume with Play key", ctx)
                await self._send_key_raw("Play")
                await asyncio.sleep(2.0)
            elif not ctx.is_playing():
                await asyncio.sleep(2.0)
        elif app_key == "paramount":
            await self._safe_select(log, query, "OK — watch")
            await asyncio.sleep(3.0)
            ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
            await self._record_screen_step(log, "Paramount: Play key to start", ctx)
            await self._send_key_raw("Play")
            await asyncio.sleep(2.5)

        played = await self._confirm_playback(log, query, ui_ctx)
        ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
        return ctx.is_playing() or played

    async def _play_via_streaming_app(
        self,
        log: list[str],
        query: str,
        app_key: str,
        title: str,
    ) -> bool:
        """Open Netflix/Paramount+ with a search keyword and OK the first result."""
        want_id = APP_MAP.get(app_key)
        if not want_id:
            return False

        ui_ctx = ReadContext(target_query=query, deep_link_app=app_key, last_action="deep_link")

        for attempt in range(2):
            ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
            if attempt:
                await self._record_screen_step(log, f"Retry #{attempt + 1}", ctx)

            if not await self._deep_link_search(app_key, query):
                await self._record_screen_step(log, f"Deep link to {app_key} failed", ctx)
                return False

            try:
                await self._wait_for_streaming_app(log, query, want_id, ui_ctx)
            except RokuEcp2Error:
                if attempt == 0:
                    continue
                raise

            if app_key == "paramount":
                await self._select_paramount_profile(log, query, ui_ctx)

            if await self._run_streaming_play_keys(log, query, app_key, title, ui_ctx):
                ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
                await self._record_screen_step(log, "Finished in-app play sequence", ctx)
                return True

            await self._record_screen_step(
                log, "Play sequence did not start — will retry", ctx,
            )

        ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
        await self._record_screen_step(log, "Finished in-app play sequence (failed)", ctx)
        return ctx.is_playing()

    async def _confirm_playback(
        self,
        log: list[str],
        query: str,
        ui_ctx: ReadContext | None = None,
        *,
        max_tries: int = 6,
    ) -> bool:
        """Poll media-player until play/startup/pause — never OK when pause (pauses Netflix)."""
        for attempt in range(max_tries):
            await asyncio.sleep(1.5)
            ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
            if ctx.is_playing():
                await self._record_screen_step(
                    log, f"Playback confirmed ({ctx.player_state})", ctx,
                )
                return True

            state = ctx.player_state
            if state == "pause":
                action, key = "Resume", "Play"
            elif state in ("startup", "buffer"):
                action, key = "Wait", None
            elif state in ("close", "none", "unknown"):
                action, key = f"Nudge #{attempt + 1}", "Play"
            else:
                action, key = f"Nudge #{attempt + 1}", "Play"

            await self._record_screen_step(
                log, f"Not playing yet ({state}) — {action}", ctx,
            )
            if key:
                await self._send_key_raw(key)
                await asyncio.sleep(2.0)

        ctx = await read_screen(self, target_query=query, ctx=ui_ctx)
        if ctx.is_playing():
            await self._record_screen_step(log, "Playback confirmed (final poll)", ctx)
            return True

        await self._record_screen_step(log, "Playback not confirmed via API", ctx)
        return False

    async def _nudge_to_preferred_provider(
        self,
        log: list[str],
        query: str,
        preferred_app: str | None,
        *,
        extra: int = 0,
    ) -> None:
        """Roku Search often highlights Prime first — Right toward Netflix/Paramount."""
        key = self._normalize_preferred_app(preferred_app)
        if not key or key == "prime":
            return
        base = {"netflix": 1, "paramount": 2, "youtube": 2, "disney": 2, "hulu": 2}
        nudges = base.get(key, 0) + extra
        for i in range(nudges):
            await self._send_key_raw("Right")
            await asyncio.sleep(0.5)
            ctx = await read_screen(self, target_query=query)
            await self._record_screen_step(log, f"Right #{i + 1} toward {key}", ctx)

    async def _press_username_ok(self, log: list[str], query: str) -> None:
        """One OK on the username already highlighted — nothing else."""
        await asyncio.sleep(5.0)
        ctx = await read_screen(self, target_query=query)
        await self._record_screen_step(log, "OK on username (Who's watching?)", ctx)
        await self._send_key_raw("Select")
        await asyncio.sleep(2.0)
        ctx = await read_screen(self, target_query=query)
        await self._record_screen_step(log, "After username OK", ctx)

    async def _leave_search_field(
        self,
        log: list[str],
        query: str,
        *,
        max_downs: int = 6,
    ) -> None:
        """Press Down until ECP reports focus left the search text field."""
        downs = 0
        for _ in range(max_downs):
            ctx = await read_screen(self, target_query=query)
            if ctx.ok_safe():
                await self._record_screen_step(
                    log, f"Left search field (downs={downs})", ctx,
                )
                return
            await self._send_key_raw("Down")
            downs += 1
            await asyncio.sleep(0.75)
            ctx = await read_screen(self, target_query=query)
            await self._record_screen_step(log, f"Down #{downs} → results", ctx)

        for rights in range(1, 4):
            ctx = await read_screen(self, target_query=query)
            if ctx.ok_safe():
                await self._record_screen_step(
                    log, f"Left search field (Right #{rights})", ctx,
                )
                return
            await self._send_key_raw("Right")
            await asyncio.sleep(0.6)
            ctx = await read_screen(self, target_query=query)
            await self._record_screen_step(log, f"Right #{rights} → results", ctx)

        ctx = await read_screen(self, target_query=query)
        if ctx.in_search_field:
            raise RokuEcp2Error(
                "Focus still in search field — refusing OK (would type garbage)",
            )

    async def _safe_select(self, log: list[str], query: str, label: str) -> None:
        ctx = await read_screen(self, target_query=query)
        if not ctx.ok_safe():
            raise RokuEcp2Error(f"Refusing OK: {label} — still in search field")
        await self._release_keys("Select")
        await self._send_key_raw("Select")
        await asyncio.sleep(2.0)
        await self._release_keys("Select")
        ctx = await read_screen(self, target_query=query)
        await self._record_screen_step(log, label, ctx)

    async def _play_search_result(
        self,
        log: list[str],
        *,
        title: str,
        preferred_app: str | None = None,
        query: str,
    ) -> None:
        """Move Down to results, pick provider, then OK — never Back/Left/Home mid-play."""
        want_id = self._preferred_app_id(preferred_app)
        await self._leave_search_field(log, query)
        await self._nudge_to_preferred_provider(log, query, preferred_app)

        await self._safe_select(log, query, f'OK — "{title}"')

        ctx = await read_screen(self, target_query=query)
        if want_id and ctx.app_id and ctx.app_id not in (want_id, "562859", ""):
            await self._record_screen_step(
                log, f"Wrong app id {ctx.app_id} — Back and nudge toward {preferred_app}", ctx,
            )
            await self._send_key_raw("Back")
            await asyncio.sleep(1.2)
            await self._nudge_to_preferred_provider(
                log, query, preferred_app, extra=2,
            )
            await self._safe_select(
                log, query, f'OK retry — "{title}" on {preferred_app}',
            )
            ctx = await read_screen(self, target_query=query)

        if ctx.on_search():
            await self._nudge_to_preferred_provider(log, query, preferred_app)
            await self._safe_select(log, query, "OK — play")
            ctx = await read_screen(self, target_query=query)

        if self._normalize_preferred_app(preferred_app) == "prime" and ctx.on_prime():
            await self._press_username_ok(log, query)

    async def roku_search_and_play(
        self,
        query: str,
        *,
        preferred_app: str | None = None,
        title: str | None = None,
        plan_summary: str | None = None,
    ) -> dict[str, Any]:
        """Read screen first, then search and play using context-driven steps."""
        query = self._sanitize_search_query(query)
        if not query:
            raise RokuEcp2Error("Empty search query")

        display_title = title or query
        log: list[str] = []
        screen_trail: list[dict[str, Any]] = []
        if plan_summary:
            log.append(f"Plan: {plan_summary}")
        log.append(f'Target search bar: "{query}"')

        for attempt in range(2):
            try:
                await self._refresh_if_stale()

                ctx = await read_screen(self, target_query=query)
                await self._record_screen_step(log, "Start", ctx)
                screen_trail.append(ctx.to_dict())

                app_key = self._normalize_preferred_app(preferred_app)
                if app_key in ("netflix", "paramount"):
                    ok = await self._play_via_streaming_app(
                        log, query, app_key, display_title,
                    )
                    ctx = await read_screen(self, target_query=query)
                    screen_trail.append(ctx.to_dict())
                    log.append(f"Done — {ctx.summary()}")
                    if not ok:
                        raise RokuEcp2Error(
                            f"Could not complete play on {app_key} "
                            f"(ended on {ctx.app_name} id {ctx.app_id})",
                        )
                    return {
                        "query": query,
                        "method": f"deep-link-{app_key}",
                        "preferred_app": preferred_app or "",
                        "steps": "\n".join(log),
                        "screen_context": ctx.to_dict(),
                        "screen_trail": screen_trail,
                    }

                if ctx.on_prime() and app_key == "prime":
                    await self._press_username_ok(log, query)
                    ctx = await read_screen(self, target_query=query)
                    screen_trail.append(ctx.to_dict())
                    log.append(f"Done — {ctx.summary()}")
                    return {
                        "query": query,
                        "method": "skip-on-prime",
                        "preferred_app": preferred_app or "",
                        "steps": "\n".join(log),
                        "screen_context": ctx.to_dict(),
                        "screen_trail": screen_trail,
                    }

                if not ctx.on_search():
                    ctx = await self._open_search_minimal(log, query)
                    screen_trail.append(ctx.to_dict())

                method = await self._ensure_search_text(query, log)
                await asyncio.sleep(2.0)
                ctx = await read_screen(self, target_query=query)
                await self._record_screen_step(log, "Results loaded", ctx)
                screen_trail.append(ctx.to_dict())

                await self._play_search_result(
                    log,
                    title=display_title,
                    preferred_app=preferred_app,
                    query=query,
                )

                ctx = await read_screen(self, target_query=query)
                screen_trail.append(ctx.to_dict())
                log.append(f"Done — {ctx.summary()}")
                return {
                    "query": query,
                    "method": method,
                    "preferred_app": preferred_app or "",
                    "steps": "\n".join(log),
                    "screen_context": ctx.to_dict(),
                    "screen_trail": screen_trail,
                }
            except RokuEcp2Error:
                if attempt == 0:
                    log.append("Connection retry…")
                    await self.connect()
                    continue
                raise
        ctx = await read_screen(self, target_query=query)
        return {
            "query": query,
            "method": "unknown",
            "steps": "\n".join(log),
            "screen_context": ctx.to_dict(),
            "screen_trail": screen_trail,
        }

    async def roku_universal_search(self, query: str) -> None:
        """Search using Roku's built-in universal search UI."""
        await self.roku_search_and_play(query)

    async def roku_search(self, query: str) -> None:
        await self.roku_search_and_play(query)


_sessions: dict[str, RokuEcp2Client] = {}


def _load_home_channel_id(host: str) -> str | None:
    try:
        config_path = Path(__file__).resolve().parent.parent / "config.json"
        if config_path.exists():
            data = json.loads(config_path.read_text())
            if data.get("host") == host:
                return data.get("home_channel_id")
    except Exception:
        pass
    return None


async def get_roku_session(host: str) -> RokuEcp2Client:
    client = _sessions.get(host)
    if client is None:
        client = RokuEcp2Client(host)
        _sessions[host] = client
    if not client._home_channel_id:
        cached = _load_home_channel_id(host)
        if cached:
            client._home_channel_id = cached
    if not client.connected:
        await client.connect()
    else:
        await client._refresh_if_stale()
    return client


async def close_roku_session(host: str) -> None:
    client = _sessions.pop(host, None)
    if client:
        await client.disconnect()