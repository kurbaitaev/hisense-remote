"""Roku universal Search — API-first, no on-screen keyboard typing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from server.roku_ecp2 import RokuEcp2Client
from server.roku_search_browse import http_search_browse, provider_ids_for_apps
from server.tv_screen import read_screen


@dataclass
class SearchPlan:
    heard: str
    query: str
    app_hint: str | None = None

    def summary(self) -> str:
        app = f" (you mentioned {self.app_hint})" if self.app_hint else ""
        return f'Searching Roku for "{self.query}"{app}.'

    def to_dict(self) -> dict[str, Any]:
        return {
            "heard": self.heard,
            "intent": "roku_search",
            "title": self.query,
            "search_text": self.query,
            "search_reason": "Your exact words — no title guessing.",
            "app": self.app_hint,
            "summary": self.summary(),
        }


@dataclass
class SearchOnlyResult:
    heard: str
    success: bool
    message: str
    plan: SearchPlan
    search_query: str
    method: str = "search-browse"
    steps: list[str] = field(default_factory=list)
    screen_context: dict[str, Any] | None = None

    def log_text(self) -> str:
        return "\n".join(self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "heard": self.heard,
            "success": self.success,
            "message": self.message,
            "search_query": self.search_query,
            "method": self.method,
            "steps": self.steps,
            "log": self.log_text(),
            "plan": self.plan.to_dict(),
            "screen_context": self.screen_context,
        }


async def _open_search_via_api(
    session: RokuEcp2Client,
    query: str,
    log: list[str],
) -> bool:
    """POST /search/browse — fills the bar without touching the keyboard."""
    ok = await http_search_browse(
        session.host,
        query,
        provider_ids=provider_ids_for_apps(),
        launch=False,
    )
    if not ok:
        log.append("search/browse HTTP failed — trying navigation fallback")
        return False

    log.append(f"POST /search/browse title={query!r}")
    for _ in range(20):
        await asyncio.sleep(0.5)
        ctx = await read_screen(session, target_query=query)
        if ctx.search_matches(query):
            log.append(f"Bar confirmed: {ctx.summary()}")
            return True
        if ctx.on_search():
            log.append(f"On Search: {ctx.summary()}")
            return True

    log.append("search/browse sent but bar not confirmed yet")
    return True


async def run_roku_search_only(
    session: RokuEcp2Client,
    *,
    heard: str,
    title: str,
    app: str | None = None,
) -> SearchOnlyResult:
    """Open Roku Search with the title via API — never Lit_ keyboard keys."""
    raw = (title or "").strip()
    if not raw:
        plan = SearchPlan(heard=heard, query="")
        return SearchOnlyResult(
            heard=heard,
            success=False,
            message="What should I search for?",
            plan=plan,
            search_query="",
        )

    query = session._sanitize_search_query(raw)
    if not query:
        plan = SearchPlan(heard=heard, query=raw, app_hint=app)
        return SearchOnlyResult(
            heard=heard,
            success=False,
            message="Could not build a search string from that.",
            plan=plan,
            search_query="",
        )

    plan = SearchPlan(heard=heard, query=query, app_hint=app)
    log: list[str] = [plan.summary()]

    await session._refresh_if_stale()
    ctx = await read_screen(session, target_query=query)

    if ctx.search_matches(query):
        log.append(f'Bar already has "{query}" — left alone.')
        method = "already-typed"
    elif await _open_search_via_api(session, query, log):
        method = "search-browse"
    else:
        method = await session._ensure_search_text(query, log)

    await asyncio.sleep(0.8)
    ctx = await read_screen(session, target_query=query)
    log.append(f"Done — {ctx.summary()}")

    bar = ctx.search_text or query
    message = f'Roku Search: "{bar}". Pick what you want on the remote.'

    return SearchOnlyResult(
        heard=heard,
        success=True,
        message=message,
        plan=plan,
        search_query=query,
        method=method,
        steps=log,
        screen_context=ctx.to_dict(),
    )
