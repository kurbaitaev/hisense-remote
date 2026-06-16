#!/usr/bin/env python3
"""Package and sideload the TV Voice Bridge channel onto a Roku TV."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx
from httpx import DigestAuth

ROOT = Path(__file__).resolve().parent.parent
ZIP_PATH = ROOT / "dist" / "tv-voice-bridge.zip"
PACKAGE_SCRIPT = ROOT / "scripts" / "package_roku_channel.sh"
CONFIG_PATH = ROOT / "config.json"


def load_host() -> str:
    if CONFIG_PATH.exists():
        host = json.loads(CONFIG_PATH.read_text()).get("host")
        if host:
            return host
    raise SystemExit("No TV host in config.json — connect once via the web UI first.")


def package() -> None:
    subprocess.run(["bash", str(PACKAGE_SCRIPT)], check=True)
    if not ZIP_PATH.exists() or ZIP_PATH.stat().st_size < 1000:
        raise SystemExit(f"Package looks empty: {ZIP_PATH}")


def install(host: str, password: str) -> None:
    data = ZIP_PATH.read_bytes()
    auth = DigestAuth("rokudev", password)
    with httpx.Client(timeout=90, auth=auth) as client:
        resp = client.post(
            f"http://{host}/plugin_install",
            files={"archive": ("tv-voice-bridge.zip", data, "application/zip")},
            data={"mysubmit": "Install", "passwd": ""},
        )
    if "Install Success" not in resp.text and "Application Received" not in resp.text:
        if "empty" in resp.text.lower():
            raise SystemExit("Install failed: zip was empty — rerun scripts/package_roku_channel.sh")
        raise SystemExit(f"Install failed (HTTP {resp.status_code}). Check password and developer mode.")
    print(f"Installed on {host} ({len(data)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Roku TV IP (default: config.json)")
    parser.add_argument("--password", default="0210", help="Developer password (default: 0210)")
    parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args()

    package()
    if args.package_only:
        print(f"Ready to upload: {ZIP_PATH}")
        return

    host = args.host or load_host()
    install(host, args.password)
    print("Launch the channel from Home → developer apps, or say “open TV Voice Bridge” after mapping.")


if __name__ == "__main__":
    main()