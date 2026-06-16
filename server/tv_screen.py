"""Read Roku TV UI state via ECP-2 (no camera). Wraps tv_ui_reader for play flow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from server.tv_ui_reader import (
    ReadContext,
    TvUiSnapshot,
    UiScreen,
    read_ui,
)

if TYPE_CHECKING:
    from server.roku_ecp2 import RokuEcp2Client

STREAMING_APP_IDS = {"12", "13", "837", "291097", "2285", "31440"}


def normalize_search_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


@dataclass
class ScreenContext:
    app_name: str
    app_id: str
    app_type: str
    ui_location: str
    search_text: str
    in_search_field: bool
    player_state: str
    phase: str
    ui: TvUiSnapshot | None = None

    def search_matches(self, query: str) -> bool:
        want = normalize_search_text(query)
        have = normalize_search_text(self.search_text)
        if not want:
            return False
        return have == want

    def on_search(self) -> bool:
        return self.app_name.lower() == "search"

    def on_prime(self) -> bool:
        return self.app_id == "13" or "prime" in self.app_name.lower()

    def on_netflix(self) -> bool:
        return self.app_id == "12"

    def on_paramount(self) -> bool:
        return self.app_id == "31440"

    def is_playing(self) -> bool:
        if self.ui:
            return self.ui.player.is_playing
        return self.player_state not in ("close", "unknown", "", "none")

    def ok_safe(self) -> bool:
        """OK types on-screen keyboard letters while focus is in the search field."""
        return not self.in_search_field

    def summary(self) -> str:
        if self.ui:
            return self.ui.summary()
        bar = f'bar="{self.search_text}"' if self.search_text else "bar=empty"
        field = "in-field" if self.in_search_field else "out-of-field"
        return (
            f"{self.phase}: {self.app_name} (id {self.app_id or '?'}) "
            f"{bar} {field} player={self.player_state}"
        )

    def to_dict(self) -> dict[str, Any]:
        base = {
            "phase": self.phase,
            "app_name": self.app_name,
            "app_id": self.app_id,
            "ui_location": self.ui_location,
            "search_text": self.search_text,
            "in_search_field": self.in_search_field,
            "player_state": self.player_state,
            "summary": self.summary(),
        }
        if self.ui:
            base["ui"] = self.ui.to_dict()
        return base


def _phase_from_ui(ui: TvUiSnapshot, target_query: str | None) -> str:
    if ui.screen == UiScreen.PLAYING:
        return "PLAYING"
    if ui.screen == UiScreen.HOME:
        return "ON_HOME"
    if ui.screen == UiScreen.ROKU_SEARCH_TYPING:
        if target_query and normalize_search_text(ui.textedit.text) == normalize_search_text(
            target_query,
        ):
            return "SEARCH_TYPED"
        return "IN_SEARCH_FIELD"
    if ui.screen == UiScreen.ROKU_SEARCH_RESULTS:
        if target_query and normalize_search_text(ui.textedit.text) == normalize_search_text(
            target_query,
        ):
            return "SEARCH_READY"
        return "ON_SEARCH"
    if ui.screen == UiScreen.NETFLIX_INFERRED_SEARCH:
        return "NETFLIX_SEARCH"
    if ui.screen == UiScreen.NETFLIX:
        return "ON_NETFLIX"
    if ui.screen == UiScreen.PARAMOUNT_INFERRED_SEARCH:
        return "PARAMOUNT_SEARCH"
    if ui.screen == UiScreen.PARAMOUNT:
        return "ON_PARAMOUNT"
    if ui.app_id == "13" or "prime" in ui.app_name.lower():
        return "ON_PRIME"
    if ui.app_id in STREAMING_APP_IDS:
        return "ON_STREAMING_APP"
    return "OTHER"


def _snapshot_to_context(ui: TvUiSnapshot, target_query: str | None) -> ScreenContext:
    return ScreenContext(
        app_name=ui.app_name,
        app_id=ui.app_id,
        app_type=ui.app_type,
        ui_location=ui.ui_location,
        search_text=ui.textedit.text,
        in_search_field=ui.textedit.in_field,
        player_state=ui.player.state,
        phase=_phase_from_ui(ui, target_query),
        ui=ui,
    )


async def read_screen(
    client: RokuEcp2Client,
    *,
    target_query: str | None = None,
    ctx: ReadContext | None = None,
) -> ScreenContext:
    read_ctx = ctx or ReadContext(target_query=target_query)
    if target_query and not read_ctx.target_query:
        read_ctx.target_query = target_query
    ui = await read_ui(client, ctx=read_ctx)
    return _snapshot_to_context(ui, target_query)