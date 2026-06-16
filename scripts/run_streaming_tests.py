#!/usr/bin/env python3
"""E2E: search > play on Netflix and Paramount+. Reports pass/fail per title."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.movie_lookup import lookup_media
from server.play_orchestrator import build_play_plan
from server.roku_ecp2 import APP_MAP, get_roku_session
from server.tv_ui_reader import ReadContext, read_ui

NETFLIX_TESTS = [
    "Play The Social Network on Netflix",
    "Play Don't Look Up on Netflix",
    "Play The Dark Knight on Netflix",
]

PARAMOUNT_TESTS = [
    "Play Top Gun Maverick on Paramount Plus",
    "Play Sonic the Hedgehog on Paramount Plus",
    "Play Transformers on Paramount Plus",
]


async def verify_playing(client, app_key: str) -> dict:
    ui = await read_ui(client)
    want = APP_MAP.get(app_key, "")
    playing = ui.player.is_playing
    on_app = ui.app_id == want or ui.player.plugin_id == want
    return {
        "playing": playing,
        "on_app": on_app,
        "app_id": ui.app_id,
        "app_name": ui.app_name,
        "player_state": ui.player.state,
        "screen": ui.screen.value,
        "summary": ui.summary(),
    }


async def run_one(client, command: str, app_key: str) -> dict:
    from server.voice_agent import parse_command

    t0 = time.monotonic()
    # Start from Home only for first test; stay in flow for speed
    ui = await read_ui(client)
    if ui.app_id not in (APP_MAP.get(app_key),):
        await client.go_home()
        await asyncio.sleep(2.5)

    cmd = await parse_command(command)
    title = cmd.title or command
    media = await lookup_media(title)
    plan = build_play_plan(
        heard=command,
        requested_title=title,
        requested_app=cmd.app or app_key,
        media=media,
    )

    result = await client.roku_search_and_play(
        plan.search_text,
        preferred_app=plan.app,
        title=plan.title,
        plan_summary=plan.summary(),
    )

    await asyncio.sleep(2)
    verify = await verify_playing(client, app_key)
    elapsed = round(time.monotonic() - t0, 1)

    on_app = verify["on_app"]
    playing = verify["playing"]
    passed = on_app and playing
    return {
        "command": command,
        "title": plan.title,
        "app": plan.app,
        "search_text": plan.search_text,
        "method": result.get("method"),
        "passed": passed,
        "elapsed_s": elapsed,
        "verify": verify,
        "steps_tail": (result.get("steps") or "")[-600:],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=None)
    parser.add_argument("--netflix-only", action="store_true")
    parser.add_argument("--paramount-only", action="store_true")
    args = parser.parse_args()

    host = args.host
    if not host:
        host = json.loads((ROOT / "config.json").read_text())["host"]

    tests: list[tuple[str, str]] = []
    if not args.paramount_only:
        tests.extend(("netflix", c) for c in NETFLIX_TESTS)
    if not args.netflix_only:
        tests.extend(("paramount", c) for c in PARAMOUNT_TESTS)

    client = await get_roku_session(host)
    results = []
    for app_key, command in tests:
        print(f"\n{'='*60}\nTEST: {command}\n{'='*60}", flush=True)
        try:
            row = await run_one(client, command, app_key)
        except Exception as exc:
            row = {
                "command": command,
                "app": app_key,
                "passed": False,
                "error": str(exc),
            }
        results.append(row)
        status = "PASS" if row.get("passed") else "FAIL"
        print(f"{status}: {row.get('title', command)} | {row.get('verify', row.get('error', ''))}", flush=True)
        await asyncio.sleep(3)

    passed = sum(1 for r in results if r.get("passed"))
    print(f"\n{'='*60}\nSUMMARY: {passed}/{len(results)} passed\n{'='*60}")
    for r in results:
        mark = "✓" if r.get("passed") else "✗"
        print(f"  {mark} {r.get('command', '?')}")
    out = ROOT / "data" / "test_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())