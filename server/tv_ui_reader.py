"""Read and interpret Roku TV UI state step-by-step via ECP-2 (no camera).

Surfaces we can *observe* on this Hisense TV (limited ECP, ECP-2 WebSocket):
  - Active app id/name/type/subtype/ui-location
  - Search bar text + focus (Roku universal Search only — textedit-id != none)
  - Media player state (play/pause/buffer/close) when the app exposes it
  - Device info (power, ecp mode, developer mode)

Surfaces we *cannot* observe without developer scene-graph or a camera:
  - Buttons, menus, result rows inside Netflix / Paramount+ / Home grids
  - Which provider icon is highlighted in Roku Search results
  - In-app search fields (textedit-id stays none)
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.roku_ecp2 import RokuEcp2Client

APP_NETFLIX = "12"
APP_PARAMOUNT = "31440"
APP_HOME_SEARCH = "562859"

STREAMING_APP_IDS = {
    APP_NETFLIX,
    APP_PARAMOUNT,
    "13",
    "837",
    "291097",
    "2285",
}


class UiScreen(str, Enum):
    PLAYING = "playing"
    HOME = "home"
    ROKU_SEARCH_TYPING = "roku_search_typing"
    ROKU_SEARCH_RESULTS = "roku_search_results"
    ROKU_SEARCH_OTHER = "roku_search_other"
    NETFLIX = "netflix"
    NETFLIX_INFERRED_SEARCH = "netflix_inferred_search"
    PARAMOUNT = "paramount"
    PARAMOUNT_INFERRED_SEARCH = "paramount_inferred_search"
    OTHER_APP = "other_app"
    UNKNOWN = "unknown"


class FocusKind(str, Enum):
    SEARCH_FIELD = "search_field"
    OUT_OF_SEARCH_FIELD = "out_of_search_field"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class SignalQuality(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNAVAILABLE = "unavailable"


@dataclass
class DeviceInfo:
    power_mode: str = ""
    ecp_mode: str = ""
    developer_enabled: bool = False
    ui_resolution: str = ""
    country: str = ""


@dataclass
class TextEditInfo:
    textedit_id: str = "none"
    text: str = ""
    in_field: bool = False
    quality: SignalQuality = SignalQuality.UNAVAILABLE

    @property
    def readable(self) -> bool:
        return self.quality == SignalQuality.OBSERVED


@dataclass
class MediaPlayerInfo:
    state: str = "none"
    plugin_id: str = ""
    plugin_name: str = ""
    position_ms: int | None = None
    duration_ms: int | None = None
    quality: SignalQuality = SignalQuality.UNAVAILABLE

    @property
    def is_playing(self) -> bool:
        return self.state in ("play", "buffer", "pause", "startup")


@dataclass
class FocusHint:
    kind: FocusKind = FocusKind.UNKNOWN
    detail: str = ""
    quality: SignalQuality = SignalQuality.INFERRED


@dataclass
class TvUiSnapshot:
    timestamp: float
    app_id: str = ""
    app_name: str = ""
    app_type: str = ""
    app_subtype: str = ""
    ui_location: str = ""
    screen: UiScreen = UiScreen.UNKNOWN
    screen_label: str = ""
    textedit: TextEditInfo = field(default_factory=TextEditInfo)
    player: MediaPlayerInfo = field(default_factory=MediaPlayerInfo)
    device: DeviceInfo = field(default_factory=DeviceInfo)
    focus: FocusHint = field(default_factory=FocusHint)
    readable: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)
    inference_note: str = ""

    def summary(self) -> str:
        parts = [self.screen_label or self.screen.value]
        if self.app_name:
            parts.append(f"{self.app_name} (id {self.app_id or '?'})")
        if self.textedit.readable:
            bar = self.textedit.text or "(empty)"
            parts.append(f'search="{bar}"')
            parts.append(
                "focus=in_search_field"
                if self.textedit.in_field
                else "focus=results_or_grid"
            )
        if self.player.quality == SignalQuality.OBSERVED:
            parts.append(f"player={self.player.state}")
        if self.inference_note:
            parts.append(f"note={self.inference_note}")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "app_id": self.app_id,
            "app_name": self.app_name,
            "app_type": self.app_type,
            "app_subtype": self.app_subtype,
            "ui_location": self.ui_location,
            "screen": self.screen.value,
            "screen_label": self.screen_label,
            "textedit": {
                "textedit_id": self.textedit.textedit_id,
                "text": self.textedit.text,
                "in_field": self.textedit.in_field,
                "quality": self.textedit.quality.value,
                "readable": self.textedit.readable,
            },
            "player": {
                "state": self.player.state,
                "plugin_id": self.player.plugin_id,
                "plugin_name": self.player.plugin_name,
                "position_ms": self.player.position_ms,
                "duration_ms": self.player.duration_ms,
                "quality": self.player.quality.value,
                "is_playing": self.player.is_playing,
            },
            "device": {
                "power_mode": self.device.power_mode,
                "ecp_mode": self.device.ecp_mode,
                "developer_enabled": self.device.developer_enabled,
                "ui_resolution": self.device.ui_resolution,
                "country": self.device.country,
            },
            "focus": {
                "kind": self.focus.kind.value,
                "detail": self.focus.detail,
                "quality": self.focus.quality.value,
            },
            "readable": self.readable,
            "blind_spots": self.blind_spots,
            "inference_note": self.inference_note,
            "summary": self.summary(),
        }


@dataclass
class UiStep:
    action: str
    intent: str
    before: TvUiSnapshot
    after: TvUiSnapshot
    delta: list[str] = field(default_factory=list)

    def explain(self) -> str:
        lines = [
            f"• {self.action} — {self.intent}",
            f"  before: {self.before.summary()}",
            f"  after:  {self.after.summary()}",
        ]
        for d in self.delta:
            lines.append(f"  Δ {d}")
        return "\n".join(lines)


@dataclass
class UiStepJournal:
    steps: list[UiStep] = field(default_factory=list)

    def record(self, action: str, intent: str, before: TvUiSnapshot, after: TvUiSnapshot) -> UiStep:
        step = UiStep(
            action=action,
            intent=intent,
            before=before,
            after=after,
            delta=_diff_snapshots(before, after),
        )
        self.steps.append(step)
        return step

    def as_text(self) -> str:
        return "\n".join(s.explain() for s in self.steps)

    def to_list(self) -> list[dict[str, Any]]:
        return [
            {
                "action": s.action,
                "intent": s.intent,
                "before": s.before.to_dict(),
                "after": s.after.to_dict(),
                "delta": s.delta,
                "explain": s.explain(),
            }
            for s in self.steps
        ]


@dataclass
class ReadContext:
    """Optional hints from the automation layer (not from the TV)."""

    target_query: str | None = None
    last_action: str | None = None
    expected_screen: UiScreen | None = None
    deep_link_app: str | None = None


def _parse_active_app(content_data: str | None) -> dict[str, str]:
    if not content_data:
        return {}
    try:
        root = ET.fromstring(base64.b64decode(content_data))
    except (ET.ParseError, ValueError):
        return {}
    if root.tag != "active-app":
        return {}
    app = root.find("app")
    if app is None:
        return {}
    return {
        "id": app.get("id", ""),
        "type": app.get("type", ""),
        "subtype": app.get("subtype", ""),
        "name": (app.text or "").strip(),
        "ui_location": app.get("ui-location", ""),
    }


def _parse_device_info(content_data: str | None) -> DeviceInfo:
    info = DeviceInfo()
    if not content_data:
        return info
    try:
        root = ET.fromstring(base64.b64decode(content_data))
    except (ET.ParseError, ValueError):
        return info
    if root.tag != "device-info":
        return info

    def _text(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None else ""

    info.power_mode = _text("power-mode")
    info.ecp_mode = _text("ecp-setting-mode")
    info.ui_resolution = _text("ui-resolution")
    info.country = _text("country")
    dev = _text("developer-enabled").lower()
    info.developer_enabled = dev in ("true", "1", "yes")
    return info


def _parse_textedit(content_data: str | None, *, on_roku_search: bool) -> TextEditInfo:
    te = TextEditInfo()
    if not content_data:
        return te
    try:
        payload = json.loads(base64.b64decode(content_data))
    except (json.JSONDecodeError, ValueError):
        return te
    state = payload.get("textedit-state")
    if not isinstance(state, dict):
        return te

    te.textedit_id = str(state.get("textedit-id", "none") or "none")
    te.text = str(state.get("text", "") or "")
    te.in_field = te.textedit_id not in ("", "none")
    if on_roku_search:
        te.quality = SignalQuality.OBSERVED
    elif te.in_field:
        te.quality = SignalQuality.OBSERVED
    return te


def _int_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_media_player(content_data: str | None) -> MediaPlayerInfo:
    mp = MediaPlayerInfo()
    if not content_data:
        return mp
    try:
        root = ET.fromstring(base64.b64decode(content_data))
    except (ET.ParseError, ValueError):
        return mp
    player = root if root.tag == "player" else root.find("player")
    if player is None:
        mp.state = "none"
        mp.quality = SignalQuality.UNAVAILABLE
        return mp

    mp.quality = SignalQuality.OBSERVED
    mp.state = player.get("state", "none") or "none"
    plugin = player.find("plugin")
    if plugin is not None:
        mp.plugin_id = plugin.get("id", "") or ""
        mp.plugin_name = (plugin.text or plugin.get("name", "") or "").strip()

    for tag, attr in (("position", "position_ms"), ("duration", "duration_ms")):
        el = player.find(tag)
        if el is not None and el.text:
            setattr(mp, attr, _int_or_none(el.text))

    return mp


def _classify_screen(
    *,
    app_id: str,
    app_name: str,
    textedit: TextEditInfo,
    player: MediaPlayerInfo,
    ctx: ReadContext | None,
) -> tuple[UiScreen, str, FocusHint, list[str], list[str], str]:
    readable: list[str] = ["active_app"]
    blind: list[str] = []
    note = ""

    if player.quality == SignalQuality.OBSERVED and player.is_playing:
        readable.append("media_player")
        return (
            UiScreen.PLAYING,
            "Video playing",
            FocusHint(FocusKind.NOT_APPLICABLE, "playback active", SignalQuality.OBSERVED),
            readable,
            ["menus", "buttons"],
            f"Playing via {player.plugin_name or app_name}",
        )

    name_lower = app_name.lower()

    if name_lower == "search" or (app_id == APP_HOME_SEARCH and name_lower == "search"):
        readable.append("search_bar")
        if textedit.in_field:
            label = "Roku Search — typing in search bar"
            screen = UiScreen.ROKU_SEARCH_TYPING
            focus = FocusHint(
                FocusKind.SEARCH_FIELD,
                "cursor in universal search field",
                SignalQuality.OBSERVED,
            )
        else:
            label = "Roku Search — results / grid (focus not in search bar)"
            screen = UiScreen.ROKU_SEARCH_RESULTS
            focus = FocusHint(
                FocusKind.OUT_OF_SEARCH_FIELD,
                "universal search: results or suggestions row",
                SignalQuality.OBSERVED,
            )
        blind.extend(["which result row", "provider icons", "buttons"])
        return screen, label, focus, readable, blind, note

    if name_lower == "home" or (app_id == APP_HOME_SEARCH and name_lower == "home"):
        readable.append("ui_location")
        blind.extend(["home row focus", "tiles", "menu buttons"])
        return (
            UiScreen.HOME,
            "Roku Home",
            FocusHint(FocusKind.UNKNOWN, "home grid focus not exposed", SignalQuality.UNAVAILABLE),
            readable,
            blind,
            note,
        )

    if app_id == APP_NETFLIX:
        readable.append("media_player")
        blind.extend(["search bar", "menus", "buttons", "result list"])
        if ctx and ctx.deep_link_app == "netflix":
            note = "Inferred: deep-linked into Netflix with a search term"
            return (
                UiScreen.NETFLIX_INFERRED_SEARCH,
                "Netflix — search/results (inferred after deep link)",
                FocusHint(FocusKind.UNKNOWN, "in-app focus not exposed", SignalQuality.INFERRED),
                readable,
                blind,
                note,
            )
        return (
            UiScreen.NETFLIX,
            "Netflix app",
            FocusHint(FocusKind.UNKNOWN, "in-app focus not exposed", SignalQuality.UNAVAILABLE),
            readable,
            blind,
            note,
        )

    if app_id == APP_PARAMOUNT:
        readable.append("media_player")
        blind.extend(["search bar", "menus", "buttons", "result list"])
        if ctx and ctx.deep_link_app == "paramount":
            note = "Inferred: deep-linked into Paramount+ with a search term"
            return (
                UiScreen.PARAMOUNT_INFERRED_SEARCH,
                "Paramount+ — search/results (inferred after deep link)",
                FocusHint(FocusKind.UNKNOWN, "in-app focus not exposed", SignalQuality.INFERRED),
                readable,
                blind,
                note,
            )
        return (
            UiScreen.PARAMOUNT,
            "Paramount+ app",
            FocusHint(FocusKind.UNKNOWN, "in-app focus not exposed", SignalQuality.UNAVAILABLE),
            readable,
            blind,
            note,
        )

    if app_id in STREAMING_APP_IDS:
        blind.extend(["in-app UI"])
        return (
            UiScreen.OTHER_APP,
            f"Streaming app — {app_name}",
            FocusHint(FocusKind.UNKNOWN, "in-app focus not exposed", SignalQuality.UNAVAILABLE),
            readable,
            blind,
            note,
        )

    blind.extend(["full UI"])
    return (
        UiScreen.UNKNOWN,
        app_name or "Unknown screen",
        FocusHint(FocusKind.UNKNOWN, "no atlas match", SignalQuality.UNAVAILABLE),
        readable,
        blind,
        note,
    )


def _diff_snapshots(before: TvUiSnapshot, after: TvUiSnapshot) -> list[str]:
    delta: list[str] = []
    if before.app_id != after.app_id or before.app_name != after.app_name:
        delta.append(f"app: {before.app_name} → {after.app_name}")
    if before.screen != after.screen:
        delta.append(f"screen: {before.screen.value} → {after.screen.value}")
    if before.textedit.text != after.textedit.text:
        delta.append(f'search text: "{before.textedit.text}" → "{after.textedit.text}"')
    if before.textedit.in_field != after.textedit.in_field:
        delta.append(
            f"search field focus: {before.textedit.in_field} → {after.textedit.in_field}",
        )
    if before.player.state != after.player.state:
        delta.append(f"player: {before.player.state} → {after.player.state}")
    if before.ui_location != after.ui_location:
        delta.append(f"ui-location: {before.ui_location} → {after.ui_location}")
    if not delta:
        delta.append("no observable change (focus/buttons may have moved)")
    return delta


async def read_ui(
    client: RokuEcp2Client,
    *,
    ctx: ReadContext | None = None,
    include_device: bool = False,
) -> TvUiSnapshot:
    """Poll every ECP-2 signal available on limited-mode TVs and interpret it."""
    ctx = ctx or ReadContext()

    app_resp = await client._send_request({"request": "query-active-app"})
    app = _parse_active_app(app_resp.get("content-data") if app_resp else None)

    app_name = app.get("name", "") or "Unknown"
    app_id = app.get("id", "") or ""
    on_roku_search = app_name.lower() == "search"

    te_resp = await client._send_request({"request": "query-textedit-state"})
    textedit = _parse_textedit(
        te_resp.get("content-data") if te_resp else None,
        on_roku_search=on_roku_search,
    )

    mp_resp = await client._send_request({"request": "query-media-player"})
    player = _parse_media_player(mp_resp.get("content-data") if mp_resp else None)

    device = DeviceInfo()
    if include_device:
        di_resp = await client._send_request({"request": "query-device-info"})
        device = _parse_device_info(di_resp.get("content-data") if di_resp else None)

    screen, label, focus, readable, blind, note = _classify_screen(
        app_id=app_id,
        app_name=app_name,
        textedit=textedit,
        player=player,
        ctx=ctx,
    )

    if player.quality == SignalQuality.OBSERVED:
        readable.append("media_player")

    return TvUiSnapshot(
        timestamp=time.time(),
        app_id=app_id,
        app_name=app_name,
        app_type=app.get("type", ""),
        app_subtype=app.get("subtype", ""),
        ui_location=app.get("ui_location", ""),
        screen=screen,
        screen_label=label,
        textedit=textedit,
        player=player,
        device=device,
        focus=focus,
        readable=sorted(set(readable)),
        blind_spots=blind,
        inference_note=note,
    )


async def press_and_read(
    client: RokuEcp2Client,
    key: str,
    *,
    intent: str = "",
    ctx: ReadContext | None = None,
    delay: float = 0.75,
) -> tuple[TvUiSnapshot, TvUiSnapshot, UiStep]:
    """Press one key, return before/after snapshots and a explained step."""
    before = await read_ui(client, ctx=ctx)
    await client._send_key_raw(key)
    await asyncio.sleep(delay)
    after = await read_ui(client, ctx=ctx)
    step = UiStep(
        action=key,
        intent=intent or key,
        before=before,
        after=after,
        delta=_diff_snapshots(before, after),
    )
    return before, after, step