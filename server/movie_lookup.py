"""Find where a movie/show is streaming (TMDB + optional Gemini fallback)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

import server.env  # noqa: F401 — load .env before reading keys
from server.apps_config import get_installed_apps
from server.brave_search import brave_available, lookup_streaming_providers
from server.llm import ask_llm

TMDB_BASE = "https://api.themoviedb.org/3"


def _tmdb_api_key() -> str:
    return os.getenv("TMDB_API_KEY", "")

# TMDB provider IDs -> our Roku app aliases (installed on this TV).
TMDB_PROVIDER_TO_APP: dict[int, str] = {
    8: "netflix",
    9: "prime",
    119: "prime",
    337: "disney",
    15: "hulu",
    350: "youtube",
    531: "paramount",
    386: "prime",  # Peacock sometimes mapped elsewhere; prefer known apps first
}

APP_PRIORITY = ("netflix", "paramount", "prime", "disney", "hulu", "youtube")


def _only_installed(providers: list[str]) -> list[str]:
    installed = set(get_installed_apps())
    return [p for p in providers if p in installed]


@dataclass
class MediaMatch:
    title: str
    year: str | None
    media_type: str
    providers: list[str]
    search_query: str | None = None
    search_variants: list[str] | None = None
    tmdb_id: int | None = None
    overview: str | None = None

    def queries_for_tv(self) -> list[str]:
        """Search strings to try on Roku universal search, best first (no year)."""
        candidates: list[str] = []
        for value in (self.search_query, self.title, *(self.search_variants or [])):
            if value and str(value).strip():
                candidates.append(str(value).strip())

        for q in list(candidates):
            if q.lower().startswith("the "):
                candidates.append(q[4:].strip())

        seen: set[str] = set()
        ordered: list[str] = []
        for q in candidates:
            key = q.casefold()
            if key not in seen:
                seen.add(key)
                ordered.append(q)
        return ordered or [self.title]

    def query_for_tv(self) -> str:
        return (self.search_query or self.title).strip()


async def _tmdb_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    api_key = _tmdb_api_key()
    if not api_key:
        return None
    query = {"api_key": api_key, **(params or {})}
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(f"{TMDB_BASE}{path}", params=query)
        if resp.status_code >= 400:
            return None
        return resp.json()


def _providers_from_tmdb(payload: dict[str, Any]) -> list[str]:
    us = (payload.get("results") or {}).get("US") or {}
    found: list[str] = []
    for bucket in ("flatrate", "rent", "buy", "free"):
        for item in us.get(bucket) or []:
            app = TMDB_PROVIDER_TO_APP.get(item.get("provider_id"))
            if app and app not in found:
                found.append(app)
    installed = set(get_installed_apps())
    ordered = [app for app in APP_PRIORITY if app in found and app in installed]
    rest = [app for app in found if app not in ordered and app in installed]
    return ordered + rest


def _match_from_tmdb_item(item: dict[str, Any], providers: list[str]) -> MediaMatch:
    media_type = item["media_type"]
    canonical = item.get("title") or item.get("name") or ""
    year = None
    if media_type == "movie":
        release = item.get("release_date") or ""
        year = release[:4] or None
    else:
        first_air = item.get("first_air_date") or ""
        year = first_air[:4] or None
    return MediaMatch(
        title=canonical,
        year=year,
        media_type=media_type,
        providers=providers,
        search_query=canonical,
        tmdb_id=item.get("id"),
        overview=item.get("overview"),
    )


async def _llm_resolve(title: str) -> MediaMatch | None:
    prompt = f"""You identify movies and TV shows for a US Roku TV voice remote.
The user said: "{title}"

Return JSON only:
{{
  "title": "official English title with correct spelling",
  "year": "YYYY or null",
  "media_type": "movie|tv",
  "search_query": "primary Roku search string (official title, no year)",
  "search_variants": ["other spellings or shorter titles to try, no years"],
  "providers": ["netflix","paramount","prime","disney","hulu","youtube"]
}}

Rules:
- Fix misspellings (e.g. "Pursuit of Happiness" -> "The Pursuit of Happyness")
- providers: best US streaming apps first, only from: netflix, paramount, prime, disney, hulu, youtube
- search_query and search_variants: no release years, just title words users would search
- search_variants: 2-4 alternates (with/without "The", common misspellings, shorter forms)
"""
    raw = await ask_llm(prompt)
    if not raw:
        return None

    import json
    import re

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(0))

    providers = [p for p in data.get("providers") or [] if p in APP_PRIORITY]
    canonical = (data.get("title") or title).strip()
    if not canonical:
        return None
    year = data.get("year")
    if year is not None:
        year = str(year).strip() or None
    search_query = (data.get("search_query") or canonical).strip()
    variants = [str(v).strip() for v in (data.get("search_variants") or []) if str(v).strip()]
    return MediaMatch(
        title=canonical,
        year=year,
        media_type=data.get("media_type") or "movie",
        providers=providers,
        search_query=search_query,
        search_variants=variants or None,
    )


async def lookup_media(title: str) -> MediaMatch | None:
    title = title.strip()
    if not title:
        return None

    llm_match = await _llm_resolve(title)

    search = await _tmdb_get(
        "/search/multi",
        {"query": (llm_match.title if llm_match else title),
         "include_adult": "false", "language": "en-US"},
    )
    if search:
        results = search.get("results") or []
        for item in results:
            if item.get("media_type") not in ("movie", "tv"):
                continue
            tmdb_id = item.get("id")
            if not tmdb_id:
                continue
            providers_payload = await _tmdb_get(
                f"/{item['media_type']}/{tmdb_id}/watch/providers",
            )
            providers = _providers_from_tmdb(providers_payload or {})
            if not providers and llm_match:
                providers = llm_match.providers
            if not providers:
                providers = await _providers_from_web(
                    item.get("title") or item.get("name") or title
                )
            match = _match_from_tmdb_item(item, _only_installed(providers))
            if llm_match:
                match.search_query = llm_match.search_query or match.search_query
                match.providers = _only_installed(
                    match.providers or llm_match.providers,
                )
            return match

    if llm_match and llm_match.providers:
        llm_match.providers = _only_installed(llm_match.providers)
        return llm_match

    providers = await _providers_from_web(title)
    if providers:
        resolved = llm_match or MediaMatch(
            title=title,
            year=None,
            media_type="movie",
            providers=[],
            search_query=title,
        )
        resolved.providers = _only_installed(providers)
        return resolved

    return llm_match


async def _providers_from_web(title: str) -> list[str]:
    if brave_available():
        brave = await lookup_streaming_providers(title)
        if brave and brave.get("providers"):
            return brave["providers"]
    guessed = await _gemini_guess(title)
    return guessed.providers if guessed else []


async def _gemini_guess(title: str) -> MediaMatch | None:
    return await _llm_resolve(title)