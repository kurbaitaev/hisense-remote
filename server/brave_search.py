"""Brave Search API helper."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

import server.env  # noqa: F401 — load .env before reading keys

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def _brave_api_key() -> str:
    return os.getenv("BRAVE_API_KEY", "")

PROVIDER_PATTERNS: list[tuple[str, str]] = [
    (r"\bnetflix\b", "netflix"),
    (r"\bparamount\+?\b|\bparamount plus\b", "paramount"),
    (r"\bprime video\b|\bamazon prime\b|\bprime\b", "prime"),
    (r"\bdisney\+?\b", "disney"),
    (r"\bhulu\b", "hulu"),
    (r"\byoutube\b", "youtube"),
]


def brave_available() -> bool:
    return bool(_brave_api_key())


async def web_search(query: str, *, count: int = 8) -> list[dict[str, str]]:
    api_key = _brave_api_key()
    if not api_key:
        return []

    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(
            BRAVE_URL,
            params={"q": query, "count": count, "country": "US", "search_lang": "en"},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
        )
        if resp.status_code == 422:
            return []
        if resp.status_code >= 400:
            return []
        data = resp.json()

    snippets: list[dict[str, str]] = []
    for item in (data.get("web") or {}).get("results") or []:
        title = str(item.get("title") or "")
        description = str(item.get("description") or "")
        extra = " ".join(str(x) for x in item.get("extra_snippets") or [])
        text = " ".join(part for part in (title, description, extra) if part).strip()
        if text:
            snippets.append({"title": title, "text": text})
    return snippets


def providers_from_snippets(snippets: list[dict[str, str]]) -> list[str]:
    blob = " ".join(item["text"] for item in snippets).lower()
    found: list[str] = []
    for pattern, app in PROVIDER_PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE) and app not in found:
            found.append(app)
    return found


async def lookup_streaming_providers(title: str) -> dict[str, Any] | None:
    """Search the web for where a title streams in the US."""
    query = f'where to watch "{title}" streaming United States'
    snippets = await web_search(query)
    if not snippets:
        return None

    providers = providers_from_snippets(snippets)
    year_match = re.search(r"\b(19|20)\d{2}\b", " ".join(s["text"] for s in snippets))
    return {
        "providers": providers,
        "year": year_match.group(0) if year_match else None,
        "sources": [s["title"] for s in snippets[:3]],
    }