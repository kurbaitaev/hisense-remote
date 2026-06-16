"""Voice/text assistant for the Hisense Roku remote."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Literal

from server.apps_config import get_installed_apps
from server.llm import llm_available, llm_provider, parse_voice_json
from server.movie_lookup import APP_PRIORITY, lookup_media
from server.play_orchestrator import build_play_plan
from server.roku_ecp2 import APP_MAP, RokuEcp2Client

Action = Literal[
    "open_app",
    "play_media",
    "search_media",
    "roku_search",
    "send_key",
    "send_keys",
    "type_text",
    "go_home",
    "unknown",
]

KEY_ALIASES = {
    "ok": "ok",
    "select": "ok",
    "enter": "ok",
    "click": "ok",
    "back": "back",
    "return": "back",
    "home": "home",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "volume up": "volume_up",
    "volume down": "volume_down",
    "mute": "mute",
    "pause": "pause",
    "play": "play",
    "stop": "stop",
    "rewind": "rewind",
    "fast forward": "fast_forward",
    "fast-forward": "fast_forward",
    "skip forward": "fast_forward",
    "skip back": "rewind",
    "channel up": "channel_up",
    "channel down": "channel_down",
    "power off": "power",
    "turn off": "power",
    "power": "power",
    "search": "search",
}


@dataclass
class VoiceCommand:
    action: Action
    app: str | None = None
    title: str | None = None
    key: str | None = None
    keys: list[str] | None = None
    text: str | None = None
    raw_text: str = ""


@dataclass
class VoiceResult:
    message: str
    action: str
    app: str | None = None
    title: str | None = None
    search_query: str | None = None
    providers: list[str] | None = None
    search_steps: str | None = None
    search_method: str | None = None
    screen_context: dict | None = None
    screen_trail: list[dict] | None = None
    plan: dict | None = None


APP_ALIASES = {
    "netflix": "netflix",
    "youtube": "youtube",
    "prime": "prime",
    "amazon": "prime",
    "prime video": "prime",
    "disney": "disney",
    "disney+": "disney",
    "hulu": "hulu",
    "paramount": "paramount",
    "paramount+": "paramount",
    "paramount plus": "paramount",
}


def _normalize_app(value: str | None) -> str | None:
    if not value:
        return None
    return APP_ALIASES.get(value.strip().lower())


def _normalize_key(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower().replace("_", " ")
    return KEY_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


def _installed_apps() -> set[str]:
    return set(get_installed_apps())


def _pick_provider(
    providers: list[str],
    preferred: str | None = None,
) -> str | None:
    installed = _installed_apps()
    if preferred:
        app = _normalize_app(preferred)
        if app and app in installed:
            return app
    for app in providers:
        if app in installed:
            return app
    for app in APP_PRIORITY:
        if app in installed:
            return app
    return None


def _parse_key_phrase(text: str) -> str | None:
    lowered = text.strip().lower()
    for alias in sorted(KEY_ALIASES, key=len, reverse=True):
        if lowered == alias or lowered.endswith(f" {alias}"):
            return KEY_ALIASES[alias]
    return None


def _parse_repeat_keys(text: str) -> VoiceCommand | None:
    match = re.search(
        r"\b(?:press|tap|hit|click|go|move|scroll)\s+"
        r"(up|down|left|right|ok|select|back|home|play|pause|mute)"
        r"(?:\s+(\d+))?\s*(?:times)?\b",
        text,
        re.I,
    )
    if not match:
        return None
    key = _normalize_key(match.group(1))
    count = int(match.group(2) or 1)
    if not key or count < 1:
        return None
    if count == 1:
        return VoiceCommand(action="send_key", key=key, raw_text=text)
    return VoiceCommand(
        action="send_keys",
        keys=[key] * min(count, 20),
        raw_text=text,
    )


def _parse_with_rules(text: str) -> VoiceCommand:
    lowered = text.strip().lower()
    if not lowered:
        return VoiceCommand(action="unknown", raw_text=text)

    if re.search(r"\b(home|go home|main menu)\b", lowered):
        return VoiceCommand(action="go_home", raw_text=text)

    repeat = _parse_repeat_keys(lowered)
    if repeat:
        return repeat

    for phrase, key in (
        ("volume up", "volume_up"),
        ("volume down", "volume_down"),
        ("turn up the volume", "volume_up"),
        ("turn down the volume", "volume_down"),
        ("mute", "mute"),
        ("unmute", "mute"),
        ("pause", "pause"),
        ("resume", "play"),
        ("channel up", "channel_up"),
        ("channel down", "channel_down"),
        ("power off", "power"),
        ("turn off the tv", "power"),
        ("turn off", "power"),
    ):
        if lowered == phrase or lowered.endswith(f" {phrase}"):
            return VoiceCommand(action="send_key", key=key, raw_text=text)

    nav_match = re.search(
        r"\b(?:press|tap|hit|click|go|move|scroll)\s+"
        r"(up|down|left|right|ok|select|back|search)\b",
        lowered,
    )
    if nav_match:
        key = _normalize_key(nav_match.group(1))
        if key:
            return VoiceCommand(action="send_key", key=key, raw_text=text)

    type_match = re.search(
        r"\b(?:type|enter|input|write)\s+(.+)$",
        lowered,
    )
    if type_match:
        return VoiceCommand(
            action="type_text",
            text=type_match.group(1).strip(),
            raw_text=text,
        )

    open_match = re.search(
        r"\b(?:open|launch|start|go to|switch to)\s+"
        r"(netflix|youtube|prime|amazon|disney\+?|hulu|paramount\+?|paramount plus)\b",
        lowered,
    )
    if open_match:
        return VoiceCommand(
            action="open_app",
            app=_normalize_app(open_match.group(1)),
            raw_text=text,
        )

    play_match = re.search(
        r"\b(?:play|watch|find|search(?:\s+for)?|show(?:\s+me)?)\s+(.+)$",
        lowered,
    )
    if play_match:
        title = play_match.group(1).strip()
        provider = (
            r"(?:amazon\s+)?(?:prime(?:\s+video)?|netflix|youtube|disney\+?|hulu|paramount\+?|paramount plus)"
        )
        for pattern in (
            rf"^(.+?)\s+on\s+({provider})\s*$",
            rf"^(.+?)\s+in\s+({provider})\s*$",
        ):
            match = re.search(pattern, title)
            if match:
                return VoiceCommand(
                    action="play_media",
                    title=match.group(1).strip(),
                    app=_normalize_app(match.group(2)),
                    raw_text=text,
                )
        return VoiceCommand(action="play_media", title=title, raw_text=text)

    single_key = _parse_key_phrase(lowered)
    if single_key:
        return VoiceCommand(action="send_key", key=single_key, raw_text=text)

    return VoiceCommand(action="unknown", raw_text=text)


async def parse_command(text: str) -> VoiceCommand:
    text = text.strip()
    if not text:
        return VoiceCommand(action="unknown", raw_text=text)

    if llm_available():
        prompt = f"""Parse this TV remote voice command for a Roku TV.

Return JSON only with this schema:
{{
  "action": "open_app|play_media|search_media|roku_search|send_key|send_keys|type_text|go_home|unknown",
  "app": "netflix|youtube|prime|disney|hulu|paramount|null",
  "title": "string or null",
  "key": "volume_up|volume_down|mute|pause|play|up|down|left|right|ok|back|home|power|channel_up|channel_down|null",
  "keys": ["up","up","down"] or null,
  "text": "string to type or null"
}}

Examples:
- "open netflix" -> open_app, app netflix
- "play Inception" -> play_media, title Inception
- "watch The Matrix on Prime" -> play_media, title The Matrix, app prime
- "search for Dune" -> search_media, title Dune
- "go home" -> go_home
- "press down" -> send_key, key down
- "click ok" -> send_key, key ok
- "press down 3 times" -> send_keys, keys ["down","down","down"]
- "type batman" -> type_text, text batman
- "volume up" -> send_key, key volume_up
- "turn off" -> send_key, key power

User command: {text!r}
"""
        parsed = await parse_voice_json(prompt)
        if parsed:
            action = parsed.get("action") or "unknown"
            if action not in {
                "open_app",
                "play_media",
                "search_media",
                "roku_search",
                "send_key",
                "send_keys",
                "type_text",
                "go_home",
                "unknown",
            }:
                action = "unknown"

            keys_raw = parsed.get("keys")
            keys: list[str] | None = None
            if isinstance(keys_raw, list) and keys_raw:
                keys = []
                for item in keys_raw:
                    key = _normalize_key(str(item))
                    if key:
                        keys.append(key)
                if not keys:
                    keys = None

            return VoiceCommand(
                action=action,  # type: ignore[arg-type]
                app=_normalize_app(parsed.get("app")),
                title=(parsed.get("title") or "").strip() or None,
                key=_normalize_key(parsed.get("key")),
                keys=keys,
                text=(parsed.get("text") or "").strip() or None,
                raw_text=text,
            )

    return _parse_with_rules(text)


async def _press_keys(
    session: RokuEcp2Client,
    keys: list[str],
    *,
    delay: float = 0.35,
) -> None:
    for key in keys:
        await session.send_key(key)
        await asyncio.sleep(delay)


async def execute_command(session: RokuEcp2Client, command: VoiceCommand) -> VoiceResult:
    if command.action == "go_home":
        await session.go_home()
        return VoiceResult(message="Opened home screen.", action="go_home")

    if command.action == "send_key" and command.key:
        await session.send_key(command.key)
        label = command.key.replace("_", " ")
        return VoiceResult(message=f"Pressed {label}.", action="send_key")

    if command.action == "send_keys" and command.keys:
        await _press_keys(session, command.keys)
        key = command.keys[0].replace("_", " ")
        return VoiceResult(
            message=f"Pressed {key} {len(command.keys)} times.",
            action="send_keys",
        )

    if command.action == "type_text" and command.text:
        await session.send_text(command.text)
        return VoiceResult(
            message=f'Typed "{command.text}".',
            action="type_text",
            search_query=command.text,
        )

    if command.action == "open_app" and command.app:
        await session.launch_app(command.app)
        label = command.app.title()
        return VoiceResult(
            message=f"Opening {label}.",
            action="open_app",
            app=command.app,
        )

    if command.action in ("play_media", "search_media"):
        title = (command.title or "").strip()
        if not title:
            return VoiceResult(message="What should I search for?", action="unknown")

        media = await lookup_media(title)
        plan = build_play_plan(
            heard=command.raw_text,
            requested_title=title,
            requested_app=command.app,
            media=media,
        )

        search_result = await session.roku_search_and_play(
            plan.search_text,
            preferred_app=plan.app,
            title=plan.title,
            plan_summary=plan.summary(),
        )

        message = plan.summary()
        if plan.app:
            message += f" Using {plan.app.title()}."

        return VoiceResult(
            message=message,
            action="play_media",
            app=plan.app,
            title=plan.title,
            search_query=search_result.get("query", plan.search_text),
            providers=plan.providers,
            search_steps=search_result.get("steps"),
            search_method=search_result.get("method"),
            screen_context=search_result.get("screen_context"),
            screen_trail=search_result.get("screen_trail"),
            plan=plan.to_dict(),
        )

    if command.action == "roku_search" and command.title:
        media = await lookup_media(command.title)
        plan = build_play_plan(
            heard=command.raw_text,
            requested_title=command.title or "",
            requested_app=command.app,
            media=media,
        )
        search_result = await session.roku_search_and_play(
            plan.search_text,
            preferred_app=plan.app,
            title=plan.title,
            plan_summary=plan.summary(),
        )
        return VoiceResult(
            message=plan.summary(),
            action="roku_search",
            title=plan.title,
            search_query=search_result.get("query", plan.search_text),
            search_steps=search_result.get("steps"),
            search_method=search_result.get("method"),
            screen_context=search_result.get("screen_context"),
            screen_trail=search_result.get("screen_trail"),
            plan=plan.to_dict(),
        )

    return VoiceResult(
        message=(
            "Try: “Play Inception”, “Open Netflix”, “Press down”, “Type batman”, "
            "or “Watch The Matrix on Prime”. "
            "Set GROQ_API_KEY or GEMINI_API_KEY for smarter commands."
        ),
        action="unknown",
    )


async def handle_voice_command(session: RokuEcp2Client, text: str) -> dict[str, Any]:
    command = await parse_command(text)
    result = await execute_command(session, command)
    return {
        "message": result.message,
        "action": result.action,
        "app": result.app,
        "title": result.title,
        "search_query": result.search_query,
        "search_method": result.search_method,
        "search_steps": result.search_steps,
        "screen_context": result.screen_context,
        "screen_trail": result.screen_trail,
        "plan": result.plan,
        "providers": result.providers,
        "parsed": {
            "action": command.action,
            "app": command.app,
            "title": command.title,
            "key": command.key,
            "keys": command.keys,
            "text": command.text,
        },
        "agent": llm_provider() or "rules",
    }