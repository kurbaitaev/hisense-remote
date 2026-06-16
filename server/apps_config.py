"""Installed streaming apps for this TV (from config.json)."""

from __future__ import annotations

import json
from pathlib import Path

from server.roku_ecp2 import APP_MAP

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def get_installed_apps() -> tuple[str, ...]:
    apps = load_config().get("installed_apps")
    if isinstance(apps, list) and apps:
        return tuple(str(a).lower() for a in apps if str(a).lower() in APP_MAP)
    return tuple(sorted(set(APP_MAP.keys()) - {"amazon"}))