"""Verify Roku TV prerequisites for full voice + automation control."""

from __future__ import annotations

import httpx

from server.roku_client import RokuTvClient
from server.roku_ecp2 import get_roku_session, RokuEcp2Error


async def check_roku_setup(host: str) -> dict:
    """Return a checklist of what's enabled and what still blocks full control."""
    roku = RokuTvClient(host)
    device = await roku.get_device_info()

    developer = (device.get("developer-enabled") or "").lower() in ("true", "1", "yes")
    ecp_mode = (device.get("ecp-setting-mode") or "unknown").lower()

    keys_ok = False
    control_mode = "none"
    try:
        session = await get_roku_session(host)
        keys_ok = True
        control_mode = "ecp-2"
    except RokuEcp2Error:
        try:
            resp = await roku._post("/keypress/Home")
            keys_ok = resp.status_code < 400
            control_mode = "http" if keys_ok else "blocked"
        except Exception:
            keys_ok = False

    sgnodes_ok = False
    sgnodes_note = ""
    if developer and ecp_mode == "enabled":
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"http://{host}:8060/query/sgnodes/all")
            if resp.status_code == 200 and resp.text.strip():
                sgnodes_ok = True
                sgnodes_note = "Scene graph readable"
            elif resp.status_code == 403:
                sgnodes_note = resp.text.strip() or "ECP blocked"
            else:
                sgnodes_note = f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            sgnodes_note = str(exc)
    elif not developer:
        sgnodes_note = "Requires developer mode"
    else:
        sgnodes_note = "Requires Control by mobile apps → Enabled"

    installer_ok = False
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            resp = await client.get(f"http://{host}/", follow_redirects=True)
        installer_ok = resp.status_code in (200, 401)
    except httpx.HTTPError:
        installer_ok = False

    steps: list[dict] = []

    def step(
        key: str,
        label: str,
        done: bool,
        *,
        how_to: str = "",
        required_for: str = "",
    ) -> None:
        steps.append({
            "key": key,
            "label": label,
            "done": done,
            "how_to": how_to,
            "required_for": required_for,
        })

    step(
        "network",
        f"TV reachable at {host}",
        True,
        required_for="All remote and voice control",
    )
    step(
        "ecp_keys",
        "Remote key control (ECP-2)",
        keys_ok,
        how_to=(
            "Settings → System → Advanced system settings → "
            "Control by mobile apps → Enabled"
        ),
        required_for="Buttons, navigation, voice key presses",
    )
    step(
        "developer_mode",
        "Developer mode",
        developer,
        how_to=(
            "Remote: Home×3, Up×2, Right, Left, Right, Left, Right → "
            "Enable installer and restart"
        ),
        required_for="Sideloaded channels, scene graph, deep debugging",
    )
    step(
        "full_ecp",
        "Full ECP (not Limited)",
        ecp_mode == "enabled",
        how_to=(
            "Settings → System → Advanced system settings → "
            "Control by mobile apps → Enabled"
        ),
        required_for="query/sgnodes, registry, app-state, exit-app",
    )
    step(
        "web_installer",
        "Developer web installer",
        installer_ok,
        how_to=f"Open http://{host} and log in as rokudev",
        required_for="Sideloading the TV Voice Bridge channel",
    )
    step(
        "scene_graph",
        "Scene graph (query/sgnodes)",
        sgnodes_ok,
        how_to=sgnodes_note or "Enable developer mode + full ECP",
        required_for="Reading focused buttons, menus, and grids on screen",
    )

    ready_voice = keys_ok
    ready_full = keys_ok and developer and ecp_mode == "enabled"

    return {
        "host": host,
        "device_name": device.get("friendly-device-name") or device.get("model-name"),
        "software_version": device.get("software-version"),
        "developer_enabled": developer,
        "ecp_mode": ecp_mode,
        "control_mode": control_mode,
        "keys_enabled": keys_ok,
        "installer_reachable": installer_ok,
        "scene_graph_available": sgnodes_ok,
        "ready_for_voice": ready_voice,
        "ready_for_full_control": ready_full,
        "steps": steps,
        "next_action": _next_action(steps, ecp_mode, developer),
    }


def _next_action(steps: list[dict], ecp_mode: str, developer: bool) -> str:
    for item in steps:
        if not item["done"]:
            if item["key"] == "ecp_keys" or item["key"] == "full_ecp":
                return (
                    "On your TV: Settings → System → Advanced system settings → "
                    "Control by mobile apps → set to Enabled (not Limited)."
                )
            if item["key"] == "developer_mode":
                return item["how_to"]
            if item["key"] == "web_installer":
                return item["how_to"]
    if developer and ecp_mode != "enabled":
        return (
            "Developer mode is on but ECP is still Limited. "
            "Enable Control by mobile apps on the TV."
        )
    return "Setup complete — use voice commands from the remote web UI."