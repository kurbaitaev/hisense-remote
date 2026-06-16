#!/usr/bin/env python3
"""Probe TV UI signals — snapshot now or step through keys with explanations."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.roku_ecp2 import get_roku_session
from server.tv_ui_reader import press_and_read, read_ui


async def main() -> None:
    parser = argparse.ArgumentParser(description="Read / probe Roku TV UI state")
    parser.add_argument("--host", default=None, help="TV IP (default: config.json)")
    parser.add_argument("--keys", nargs="*", help="Keys to press in sequence (e.g. Down Select)")
    parser.add_argument("--device", action="store_true", help="Include device-info")
    args = parser.parse_args()

    host = args.host
    if not host:
        cfg = json.loads((ROOT / "config.json").read_text())
        host = cfg.get("host")
    if not host:
        print("No host — set config.json or pass --host", file=sys.stderr)
        sys.exit(1)

    client = await get_roku_session(host)

    if not args.keys:
        ui = await read_ui(client, include_device=args.device)
        print(json.dumps(ui.to_dict(), indent=2))
        return

    for key in args.keys:
        before, after, step = await press_and_read(client, key, intent=f"probe {key}")
        print(step.explain())
        print()


if __name__ == "__main__":
    asyncio.run(main())