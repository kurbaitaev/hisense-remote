#!/usr/bin/env python3
"""Find Roku TVs using every discovery method. Run in Terminal.app."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> None:
    from server.discovery import _get_local_ips, _subnet_prefixes, discover_tvs_with_diagnostics
    from server.roku_client import probe_roku
    from server.roku_ssdp import discover_roku_ssdp, ips_from_arp_table

    print("=== Hisense Remote — TV finder ===\n")
    print("local_ips:", _get_local_ips())
    print("scan_subnets:", _subnet_prefixes())
    print("arp candidates:", ips_from_arp_table()[:20])

    print("\n--- SSDP (roku:ecp multicast) ---")
    ssdp = discover_roku_ssdp(timeout=4.0)
    print(json.dumps(ssdp, indent=2) if ssdp else "(none)")

    saved = None
    cfg = ROOT / "config.json"
    if cfg.exists():
        saved = json.loads(cfg.read_text()).get("host")
    if saved:
        print(f"\n--- saved host {saved} ---")
        ok = await probe_roku(saved, timeout=3.0)
        print("reachable:", ok)

    print("\n--- full discover_tvs ---")
    result = await discover_tvs_with_diagnostics(platform="roku", timeout=5.0)
    print(json.dumps(result, indent=2))

    if result["tvs"]:
        print(f"\n✓ Found: {result['tvs'][0]['ip']} — open the remote and Connect")
    else:
        print("\n✗ No TV found. On TV: Settings → Network → About → note IP, enter manually.")


if __name__ == "__main__":
    asyncio.run(main())
