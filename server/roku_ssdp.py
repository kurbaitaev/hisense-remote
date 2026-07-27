"""SSDP discovery for Roku TVs (roku:ecp on UDP 1900)."""

from __future__ import annotations

import re
import socket
import struct
from typing import Any
from urllib.parse import urlparse

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: roku:ecp\r\n"
    "\r\n"
).encode()


def _ip_from_location(value: str) -> str | None:
    try:
        parsed = urlparse(value.strip())
        host = parsed.hostname
        if host and re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
            return host
    except Exception:
        pass
    return None


def discover_roku_ssdp(timeout: float = 3.0) -> list[dict[str, Any]]:
    """Multicast M-SEARCH for roku:ecp devices."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.4)
        try:
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_TTL,
                2,
            )
        except OSError:
            pass

        import time

        # Multicast is lossy — burst + re-send (same idea as Roam SSDPDiscovery)
        for _ in range(3):
            try:
                sock.sendto(MSEARCH, (SSDP_ADDR, SSDP_PORT))
            except OSError:
                return []
            time.sleep(0.05)

        deadline = time.monotonic() + timeout
        next_resend = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if time.monotonic() >= next_resend:
                try:
                    sock.sendto(MSEARCH, (SSDP_ADDR, SSDP_PORT))
                except OSError:
                    pass
                next_resend = time.monotonic() + 1.0
            try:
                data, addr = sock.recvfrom(8192)
            except TimeoutError:
                continue
            except OSError:
                break

            text = data.decode("utf-8", errors="replace")
            location = None
            friendly = None
            for line in text.split("\r\n"):
                if line.upper().startswith("LOCATION:"):
                    location = line.split(":", 1)[1].strip()
                if line.upper().startswith("SERVER:") and "roku" in line.lower():
                    friendly = line.split(":", 1)[1].strip()[:80]

            ip = _ip_from_location(location or "")
            if not ip and addr and len(addr) >= 1:
                candidate = addr[0]
                if re.match(r"^\d+\.\d+\.\d+\.\d+$", candidate) and (
                    "roku" in text.lower() or "roku:ecp" in text.lower()
                ):
                    ip = candidate
            if not ip or ip in seen:
                continue
            seen.add(ip)
            found.append({
                "ip": ip,
                "platform": "roku",
                "name": friendly or f"Roku ({ip})",
                "model": "",
                "vendor": "Roku",
                "via": "ssdp",
            })
    finally:
        sock.close()

    return found


def ips_from_arp_table() -> list[str]:
    """Parse `arp -a` for private LAN IPs (hints when route detection fails)."""
    import subprocess

    try:
        result = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return []

    ips: list[str] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", line)
        if not match:
            continue
        ip = match.group(1)
        if ip.startswith(("192.168.", "10.")) and ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips
