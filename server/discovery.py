"""Wi-Fi discovery for Roku and VIDAA TVs."""

from __future__ import annotations

import asyncio
import json
import re
import socket
import time
from pathlib import Path
from typing import Any

from zeroconf import ServiceBrowser, Zeroconf

from server.roku_client import RokuTvClient, probe_roku
from server.tv_client import probe_vidaa

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

ROKU_SERVICE = "_roku-rsp._tcp.local."

# When route detection fails (sandbox / odd NIC), still try common home LANs.
COMMON_SUBNETS = ("192.168.0", "192.168.1", "192.168.4", "10.0.0")


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


async def _probe_saved_roku(saved_host: str | None) -> dict[str, Any] | None:
    if not saved_host:
        return None
    if await probe_roku(saved_host, timeout=2.5):
        return await _describe_roku(saved_host)
    return None


async def discover_tvs(
    *,
    platform: str = "auto",
    timeout: float = 4.0,
) -> list[dict[str, Any]]:
    """Discover TVs on the local network."""
    found: list[dict[str, Any]] = []
    seen_ips: set[str] = set()

    def merge(devices: list[dict[str, Any]]) -> None:
        for device in devices:
            ip = device.get("ip")
            if ip and ip not in seen_ips:
                seen_ips.add(ip)
                found.append(device)

    if platform in ("auto", "roku"):
        saved_host = _load_saved_roku_host()
        saved_device = await _probe_saved_roku(saved_host)
        if saved_device:
            merge([saved_device])
            return found

        # Method 1: SSDP (Roku's primary discovery protocol)
        try:
            from server.roku_ssdp import discover_roku_ssdp

            ssdp_devices = await asyncio.to_thread(discover_roku_ssdp, min(timeout, 3.5))
        except Exception:
            ssdp_devices = []
        merge(ssdp_devices)
        if found:
            return found

        # Method 2: mDNS
        try:
            mdns_devices = await asyncio.to_thread(
                discover_roku_mdns, min(timeout, 3.5)
            )
        except Exception:
            mdns_devices = []
        merge(mdns_devices)
        if found:
            return found

        # Method 3: probe ARP table candidates (fast, no full subnet scan)
        merge(await _probe_arp_candidates())
        if found:
            return found

        merge(await _scan_subnet_for_roku())

    if platform in ("auto", "vidaa") and not found:
        merge(await _scan_subnet_for_vidaa())

    return found


async def discover_tvs_with_diagnostics(
    *,
    platform: str = "auto",
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Like discover_tvs but includes why saved host / scan failed."""
    saved_host = _load_saved_roku_host() if platform in ("auto", "roku") else None
    saved_reachable: bool | None = None
    if saved_host:
        saved_reachable = await probe_roku(saved_host, timeout=2.5)

    tvs = await discover_tvs(platform=platform, timeout=timeout)

    # If full scan missed it, still surface a reachable saved host.
    if not tvs and saved_host and saved_reachable:
        from server.discovery import _describe_roku

        tvs = [await _describe_roku(saved_host)]

    return {
        "tvs": tvs,
        "saved_host": saved_host,
        "saved_host_reachable": saved_reachable,
        "local_ips": _get_local_ips(),
        "scan_subnets": _subnet_prefixes(),
    }


async def _probe_arp_candidates() -> list[dict[str, Any]]:
    """Try Roku ECP on IPs recently seen on the LAN (from arp -a)."""
    from server.roku_ssdp import ips_from_arp_table

    candidates = ips_from_arp_table()
    saved = _load_saved_roku_host()
    if saved and saved not in candidates:
        candidates.insert(0, saved)

    devices: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(16)

    async def check(ip: str) -> None:
        async with sem:
            if await probe_roku(ip, timeout=1.5):
                devices.append(await _describe_roku(ip))

    await asyncio.gather(*[check(ip) for ip in candidates[:64]])
    return devices


async def _scan_subnet_for_roku() -> list[dict[str, Any]]:
    """Scan local subnet(s) for Roku ECP on port 8060."""
    prefixes = _subnet_prefixes()
    if not prefixes:
        return []

    found_ips: list[str] = []
    seen: set[str] = set()
    sem = asyncio.Semaphore(64)

    async def check(host: str) -> None:
        async with sem:
            if host in seen:
                return
            if await probe_roku(host, timeout=1.2):
                if host not in seen:
                    seen.add(host)
                    found_ips.append(host)

    hosts: list[str] = []
    for prefix in prefixes:
        hosts.extend(f"{prefix}.{i}" for i in range(1, 255))

    await asyncio.gather(*[check(host) for host in hosts])

    devices: list[dict[str, Any]] = []
    for ip in found_ips:
        devices.append(await _describe_roku(ip))
    return devices


async def _scan_subnet_for_vidaa() -> list[dict[str, Any]]:
    prefixes = _subnet_prefixes()
    if not prefixes:
        return []
    found: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(50)

    async def check_ip(ip: str) -> None:
        async with sem:
            if await asyncio.to_thread(probe_vidaa, ip, use_ssl=True):
                found.append({"ip": ip, "platform": "vidaa", "name": ip})
            elif await asyncio.to_thread(probe_vidaa, ip, use_ssl=False):
                found.append({"ip": ip, "platform": "vidaa", "name": ip})

    hosts = [f"{prefix}.{i}" for prefix in prefixes for i in range(1, 255)]
    await asyncio.gather(*[check_ip(host) for host in hosts])
    return found


def _get_local_ip() -> str | None:
    ips = _get_local_ips()
    return ips[0] if ips else None


def _subnet_prefix(ip: str) -> str | None:
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        if not all(0 <= int(p) <= 255 for p in parts):
            return None
    except ValueError:
        return None
    return ".".join(parts[:3])


def _get_local_ips() -> list[str]:
    """Collect LAN IPs — VPN or multi-NIC setups can make a single 8.8.8.8 route wrong."""
    seen: set[str] = set()
    ordered: list[str] = []

    def add(ip: str) -> None:
        if not ip or ip.startswith("127.") or ip in seen:
            return
        seen.add(ip)
        ordered.append(ip)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            add(s.getsockname()[0])
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass

    return ordered


def _subnet_prefixes() -> list[str]:
    """Unique /24 prefixes to scan (local NICs + saved TV + common home LANs)."""
    prefixes: list[str] = []
    seen: set[str] = set()

    def add_prefix(ip_or_prefix: str | None) -> None:
        if not ip_or_prefix:
            return
        if re.match(r"^\d+\.\d+\.\d+$", ip_or_prefix):
            prefix = ip_or_prefix
        else:
            prefix = _subnet_prefix(ip_or_prefix)
        if prefix and prefix not in seen:
            seen.add(prefix)
            prefixes.append(prefix)

    for ip in _get_local_ips():
        add_prefix(ip)
    add_prefix(_load_saved_roku_host())
    for prefix in COMMON_SUBNETS:
        add_prefix(prefix)
    return prefixes