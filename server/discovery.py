"""Wi-Fi discovery for Roku and VIDAA TVs."""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Any

from zeroconf import ServiceBrowser, Zeroconf

from server.roku_client import RokuTvClient, probe_roku
from server.tv_client import probe_vidaa

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

ROKU_SERVICE = "_roku-rsp._tcp.local."


def discover_roku_mdns(timeout: float = 3.0) -> list[dict[str, Any]]:
    """Find Roku TVs via mDNS (fast when it works)."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    class Listener:
        def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name, timeout=1500)
            if not info:
                return
            addresses = info.parsed_addresses()
            if not addresses:
                return
            ip = addresses[0]
            if ip in seen:
                return
            seen.add(ip)

            props = {}
            if info.properties:
                props = {
                    k.decode() if isinstance(k, bytes) else k: (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in info.properties.items()
                }

            friendly = name.removesuffix("._roku-rsp._tcp.local.")
            found.append({
                "ip": ip,
                "platform": "roku",
                "name": friendly,
                "model": props.get("model", ""),
                "vendor": props.get("vendor", ""),
            })

        def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass

        def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
            pass

    zc = Zeroconf()
    try:
        browser = ServiceBrowser(zc, ROKU_SERVICE, Listener())
        time.sleep(timeout)
        browser.cancel()
    finally:
        zc.close()

    return found


def _load_saved_roku_host() -> str | None:
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text())
            if data.get("platform") == "roku" and data.get("host"):
                return str(data["host"])
    except Exception:
        pass
    return None


async def _describe_roku(ip: str) -> dict[str, Any]:
    name = ip
    model = ""
    try:
        info = await RokuTvClient(ip, timeout=2.0).get_device_info()
        name = info.get("friendly-device-name") or info.get("model-name") or ip
        model = info.get("model-name", "")
    except Exception:
        pass
    return {
        "ip": ip,
        "platform": "roku",
        "name": name,
        "model": model,
    }


async def discover_tvs(
    *,
    platform: str = "auto",
    timeout: float = 4.0,
) -> list[dict[str, Any]]:
    """Discover TVs on the local network."""
    found: list[dict[str, Any]] = []
    seen_ips: set[str] = set()

    if platform in ("auto", "roku"):
        saved_host = _load_saved_roku_host()
        if saved_host and await probe_roku(saved_host, timeout=2.0):
            device = await _describe_roku(saved_host)
            seen_ips.add(saved_host)
            found.append(device)

        if not found:
            mdns_devices = await asyncio.to_thread(
                discover_roku_mdns, min(timeout, 3.0)
            )
            for device in mdns_devices:
                if device["ip"] not in seen_ips:
                    seen_ips.add(device["ip"])
                    found.append(device)

        # Subnet scan is slow (~10s). Skip it when we already found a TV.
        if not found:
            for device in await _scan_subnet_for_roku():
                if device["ip"] not in seen_ips:
                    seen_ips.add(device["ip"])
                    found.append(device)

    if platform in ("auto", "vidaa") and not found:
        for device in await _scan_subnet_for_vidaa():
            if device["ip"] not in seen_ips:
                found.append(device)

    return found


async def _scan_subnet_for_roku() -> list[dict[str, Any]]:
    """Scan local subnet for Roku ECP on port 8060."""
    local_ip = _get_local_ip()
    if not local_ip:
        return []

    prefix = ".".join(local_ip.split(".")[:3])
    found_ips: list[str] = []
    stop = asyncio.Event()
    sem = asyncio.Semaphore(64)

    async def check(host: str) -> None:
        if stop.is_set():
            return
        async with sem:
            if stop.is_set():
                return
            if await probe_roku(host, timeout=0.8):
                found_ips.append(host)
                stop.set()

    await asyncio.gather(*[check(f"{prefix}.{i}") for i in range(1, 255)])

    devices: list[dict[str, Any]] = []
    for ip in found_ips:
        devices.append(await _describe_roku(ip))
    return devices


async def _scan_subnet_for_vidaa() -> list[dict[str, Any]]:
    local_ip = _get_local_ip()
    if not local_ip:
        return []

    prefix = ".".join(local_ip.split(".")[:3])
    found: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(50)

    async def check_ip(ip: str) -> None:
        async with sem:
            if await asyncio.to_thread(probe_vidaa, ip, use_ssl=True):
                found.append({"ip": ip, "platform": "vidaa", "name": ip})
            elif await asyncio.to_thread(probe_vidaa, ip, use_ssl=False):
                found.append({"ip": ip, "platform": "vidaa", "name": ip})

    await asyncio.gather(*[check_ip(f"{prefix}.{i}") for i in range(1, 255)])
    return found


def _get_local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None