"""See the TV screen via phone camera + Gemini vision, then decide the next remote key."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import httpx

import server.env  # noqa: F401

from server.llm import gemini_available

GEMINI_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

ALLOWED_KEYS = frozenset({
    "up", "down", "left", "right", "ok", "back", "home",
    "play", "pause", "rewind", "fast_forward",
    "volume_up", "volume_down", "mute",
    "channel_up", "channel_down",
    "search", "power", "none", "wait",
})

VISION_PROMPT = """You are the eyes for a Roku TV voice/remote bot. The user photographs their TV screen with a phone.

You also receive limited data from the TV API (active app name, player state) — trust the PHOTO for menus, focus, and text.

Return JSON only:
{
  "screen_summary": "1-2 sentences: what screen this is",
  "visible_text": ["important on-screen labels, titles, buttons"],
  "focused_item": "what looks highlighted/selected, or null",
  "profiles_visible": false,
  "profile_names": [],
  "on_search_results": false,
  "is_playing_video": false,
  "recommended_key": "up|down|left|right|ok|back|home|play|pause|search|none|wait",
  "action_reason": "why this key is the single best next press",
  "goal_status": "in_progress|done|blocked|unknown",
  "confidence": 0.0
}

Rules:
- recommended_key is ONE remote key for the next step only
- use "none" if looking is enough and no key is needed yet
- use "wait" if the screen is still loading
- on Paramount/Netflix "Who's Watching", describe which profile is highlighted; do NOT assume Kids
- if the user's goal is already achieved (video playing, app open), goal_status=done and recommended_key=none
- confidence 0.0-1.0

User goal: {goal}

TV API context (may be incomplete):
{ecp_context}
"""


def vision_available() -> bool:
    return gemini_available()


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_key(value: str | None) -> str:
    if not value:
        return "none"
    key = str(value).strip().lower().replace(" ", "_")
    aliases = {
        "select": "ok",
        "enter": "ok",
        "confirm": "ok",
    }
    key = aliases.get(key, key)
    return key if key in ALLOWED_KEYS else "none"


async def analyze_tv_photo(
    image_bytes: bytes,
    *,
    goal: str = "Describe the TV screen and suggest the best next remote button.",
    ecp_context: dict[str, Any] | None = None,
    mime_type: str = "image/jpeg",
    timeout: float = 45.0,
) -> dict[str, Any]:
    if not vision_available():
        raise RuntimeError("GEMINI_API_KEY not configured — vision requires Gemini.")

    if len(image_bytes) < 2000:
        raise RuntimeError("Image too small — point the phone camera at the TV and try again.")

    api_key = os.getenv("GEMINI_API_KEY")
    assert api_key

    ctx_text = json.dumps(ecp_context or {}, indent=2)
    prompt = VISION_PROMPT.format(goal=goal.strip() or "Observe the TV.", ecp_context=ctx_text)

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            GEMINI_URL,
            params={"key": api_key},
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Vision API failed ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Vision API returned no analysis.")
    parts = candidates[0].get("content", {}).get("parts") or []
    raw = str(parts[0].get("text", "")).strip() if parts else ""
    parsed = _extract_json(raw)
    if not parsed:
        raise RuntimeError("Vision model did not return valid JSON.")

    key = _normalize_key(parsed.get("recommended_key"))
    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    return {
        "screen_summary": str(parsed.get("screen_summary", "")).strip(),
        "visible_text": parsed.get("visible_text") or [],
        "focused_item": parsed.get("focused_item"),
        "profiles_visible": bool(parsed.get("profiles_visible")),
        "profile_names": parsed.get("profile_names") or [],
        "on_search_results": bool(parsed.get("on_search_results")),
        "is_playing_video": bool(parsed.get("is_playing_video")),
        "recommended_key": key,
        "action_reason": str(parsed.get("action_reason", "")).strip(),
        "goal_status": str(parsed.get("goal_status", "unknown")).strip(),
        "confidence": max(0.0, min(1.0, confidence)),
        "goal": goal,
        "model": GEMINI_MODEL,
    }


async def vision_act(
    session,
    image_bytes: bytes,
    *,
    goal: str,
    ecp_context: dict[str, Any] | None = None,
    mime_type: str = "image/jpeg",
    min_confidence: float = 0.35,
) -> dict[str, Any]:
    """Analyze a photo and optionally press one remote key."""
    from server.roku_ecp2 import RokuEcp2Client

    if not isinstance(session, RokuEcp2Client):
        raise RuntimeError("Vision control requires a Roku TV connection.")

    analysis = await analyze_tv_photo(
        image_bytes,
        goal=goal,
        ecp_context=ecp_context,
        mime_type=mime_type,
    )

    key = analysis["recommended_key"]
    acted = False
    act_message = "No key pressed."

    if key not in ("none", "wait") and analysis["confidence"] >= min_confidence:
        await session.send_key(key)
        acted = True
        act_message = f"Pressed {key.replace('_', ' ')}."
    elif key == "wait":
        act_message = "Screen still loading — wait and capture again."
    elif key in ("none",):
        act_message = "Observed only — no key needed."
    else:
        act_message = f"Low confidence ({analysis['confidence']:.0%}) — review before acting."

    return {
        **analysis,
        "acted": acted,
        "message": act_message,
    }