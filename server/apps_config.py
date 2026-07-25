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


def get_paramount_profile_down_presses() -> int:
    """Down-presses on Paramount+ 'Who's Watching' before OK.

    Profiles are stacked vertically on this TV: top = adult, below = Kids.
    0 = OK on whoever is already highlighted (adult is on top by default).
    1 = Down once, then OK (only if adult profile is below Kids).
    """
    paramount = load_config().get("paramount")
    if isinstance(paramount, dict):
        try:
            legacy = paramount.get("profile_rights")
            if legacy is not None and "profile_down_presses" not in paramount:
                return max(0, int(legacy))
            return max(0, int(paramount.get("profile_down_presses", 0)))
        except (TypeError, ValueError):
            pass
    return 0