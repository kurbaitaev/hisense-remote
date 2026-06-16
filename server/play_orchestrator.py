"""Build a human-readable play plan before touching the TV."""

from __future__ import annotations

from dataclasses import dataclass, field

from server.apps_config import get_installed_apps
from server.movie_lookup import APP_PRIORITY, MediaMatch


def _pick_provider(providers: list[str], preferred: str | None = None) -> str | None:
    installed = set(get_installed_apps())
    if preferred and preferred in installed:
        return preferred
    for app in providers:
        if app in installed:
            return app
    for app in APP_PRIORITY:
        if app in installed:
            return app
    return None


@dataclass
class PlayPlan:
    heard: str
    intent: str
    title: str
    year: str | None
    search_text: str
    search_reason: str
    app: str | None
    app_reason: str
    providers: list[str] = field(default_factory=list)
    steps_planned: list[str] = field(default_factory=list)

    def summary(self) -> str:
        year = f" ({self.year})" if self.year else ""
        app = f" on {self.app.title()}" if self.app else ""
        return (
            f"You want to watch “{self.title}”{year}{app}. "
            f"I'll search Roku for “{self.search_text}”."
        )

    def to_dict(self) -> dict:
        return {
            "heard": self.heard,
            "intent": self.intent,
            "title": self.title,
            "year": self.year,
            "search_text": self.search_text,
            "search_reason": self.search_reason,
            "app": self.app,
            "app_reason": self.app_reason,
            "providers": self.providers,
            "steps_planned": self.steps_planned,
            "summary": self.summary(),
        }


def build_play_plan(
    *,
    heard: str,
    requested_title: str,
    requested_app: str | None,
    media: MediaMatch | None,
) -> PlayPlan:
    title = media.title if media else requested_title.strip()
    year = media.year if media else None
    providers = media.providers if media else []
    preferred = _pick_provider(providers, requested_app)
    search_text = media.query_for_tv() if media else requested_title.strip()

    if requested_app:
        app_reason = f"You asked for {requested_app.title()}."
    elif preferred and providers:
        app_reason = f"Looks available on {preferred.title()} (first match on your TV)."
    elif preferred:
        app_reason = f"Best guess: {preferred.title()}."
    else:
        app_reason = "No streaming app pinned — I'll use the first Roku result."

    if media and media.search_query and media.search_query != title:
        search_reason = (
            f"Corrected your request to the official title “{title}” "
            f"for Roku search."
        )
    elif media:
        search_reason = f"Using official title “{title}” for Roku search."
    else:
        search_reason = "Using your words as-is (no movie database match)."

    if preferred in ("netflix", "paramount"):
        steps = [
            f"Open {preferred.title()} search directly",
            f'Search for "{search_text}" inside the app',
            f'OK on “{title}”, then OK to play',
        ]
    else:
        steps = [
            "Read TV screen (app, search bar, focus)",
            "Open Roku Search only if not already there (no Back storm)",
            f'Type "{search_text}" only if bar does not match',
            "Down to results (never Back/Left/Home mid-play)",
            f'OK on “{title}”, then OK to play',
        ]
        if preferred == "prime":
            steps.append("OK on the highlighted Prime username")
        elif preferred:
            steps.append(f"Start on {preferred.title()}")

    return PlayPlan(
        heard=heard,
        intent="play_movie",
        title=title,
        year=year,
        search_text=search_text,
        search_reason=search_reason,
        app=preferred,
        app_reason=app_reason,
        providers=providers,
        steps_planned=steps,
    )