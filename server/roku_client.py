"""Roku / Hisense Roku TV client via ECP (port 8060)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx

ROKU_PORT = 8060

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

# App IDs vary by region/model — these work on this Hisense Roku TV.
APP_MAP = {
    "netflix": "12",
    "youtube": "195316",
    "amazon": "13",
    "prime": "13",
    "disney": "291097",
    "hulu": "2285",
}

ECP_LIMITED_MSG = (
    "Roku is blocking remote buttons. On your TV: "
    "Settings → System → Advanced system settings → "
    "Control by mobile apps → Enabled"
)


class RokuTvError(Exception):
    pass


class RokuControlError(RokuTvError):
    pass


class RokuTvClient:
    def __init__(self, host: str, timeout: float = 5.0):
        self.host = host
        self.base_url = f"http://{host}:{ROKU_PORT}"
        self.timeout = timeout

    async def _post(self, path: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(f"{self.base_url}{path}")

    async def _get(self, path: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.get(f"{self.base_url}{path}")

    def _check_key_response(self, resp: httpx.Response, key: str) -> None:
        if resp.status_code == 403:
            raise RokuControlError(ECP_LIMITED_MSG)
        if resp.status_code >= 400:
            raise RokuControlError(f"TV rejected key '{key}' (HTTP {resp.status_code})")

    def _check_launch_response(self, resp: httpx.Response, app: str) -> None:
        if resp.status_code == 404:
            raise RokuControlError(f"{app} is not installed on this TV")
        if resp.status_code == 403:
            raise RokuControlError(ECP_LIMITED_MSG)
        if resp.status_code >= 400:
            raise RokuControlError(f"Could not launch {app} (HTTP {resp.status_code})")

    async def send_key(self, key: str) -> None:
        roku_key = KEY_MAP.get(key, key)
        resp = await self._post(f"/keypress/{roku_key}")
        self._check_key_response(resp, key)

    async def send_key_hold(self, key: str) -> None:
        roku_key = KEY_MAP.get(key, key)
        down = await self._post(f"/keydown/{roku_key}")
        self._check_key_response(down, key)
        up = await self._post(f"/keyup/{roku_key}")
        self._check_key_response(up, key)

    async def launch_app(self, app_id: str, *, label: str = "app") -> None:
        resp = await self._post(f"/launch/{app_id}")
        self._check_launch_response(resp, label)

    async def launch_app_by_name(self, name: str) -> None:
        app_id = APP_MAP.get(name.lower())
        if not app_id:
            raise RokuControlError(f"Unknown app: {name}")
        await self.launch_app(app_id, label=name)

    def _parse_xml(self, text: str) -> dict[str, str]:
        root = ET.fromstring(text)
        return {child.tag: (child.text or "").strip() for child in root}

    async def get_device_info(self) -> dict[str, Any]:
        resp = await self._get("/query/device-info")
        resp.raise_for_status()
        info = self._parse_xml(resp.text)
        if info.get("model-name") and not info.get("friendly-device-name"):
            vendor = info.get("vendor-name", "")
            model = info.get("model-name", "")
            info["friendly-device-name"] = f"{vendor} {model}".strip()
        return info

    async def get_active_app(self) -> dict[str, str]:
        resp = await self._get("/query/active-app")
        resp.raise_for_status()
        return self._parse_xml(resp.text)

    async def get_ecp_mode(self) -> str:
        info = await self.get_device_info()
        return info.get("ecp-setting-mode", "unknown")

    async def keys_enabled(self) -> bool:
        """True if keypress commands are allowed."""
        try:
            resp = await self._post("/keypress/Home")
            return resp.status_code < 400
        except httpx.HTTPError:
            return False


async def probe_roku(host: str, timeout: float = 3.0) -> bool:
    try:
        client = RokuTvClient(host, timeout=timeout)
        await client.get_device_info()
        return True
    except Exception:
        return False