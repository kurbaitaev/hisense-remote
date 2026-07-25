"""Voice/text commands for the Hisense Roku remote — search-only for play/watch requests."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Literal

from server.llm import llm_available, llm_provider, parse_voice_json
from server.roku_ecp2 import RokuEcp2Client
from server.smart_agent import run_play_goal

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

SEARCH_ACTIONS = frozenset({"play_media", "search_media", "roku_search"})
FAST_ACTIONS = frozenset({"go_home", "send_key", "send_keys", "type_text", "open_app"})


def _normalize_app(value: str | None) -> str | None:
    if not value:
        return None
    return APP_ALIASES.get(value.strip().lower())


def _normalize_key(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower().replace("_", " ")
    return KEY_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


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

The assistant opens Roku universal Search and types the user's exact words.
It never auto-plays, never presses OK/Down after typing, and never rewrites sports/events into movies.

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
- "type batman" -> type_text, text batman

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

    if command.action in SEARCH_ACTIONS:
        title = (command.title or "").strip()
        if not title:
            return VoiceResult(message="What should I search for?", action="unknown")

        agent_result = await run_play_goal(
            session,
            heard=command.raw_text,
            title=title,
            app=command.app,
        )
        plan = agent_result.plan or {}
        display_title = plan.get("title") or title
        search_query = plan.get("search_text") or title
        year = plan.get("year")
        year_suffix = f" ({year})" if year else ""
        app_name = plan.get("app")

        if agent_result.success:
            message = f"Playing “{display_title}”{year_suffix}."
            if app_name:
                message = f"Playing “{display_title}”{year_suffix} on {app_name.title()}."
        else:
            message = agent_result.message

        return VoiceResult(
            message=message,
            action="play_media" if agent_result.success else "roku_search",
            app=app_name,
            title=display_title,
            search_query=search_query,
            providers=plan.get("providers"),
            search_steps=agent_result.log_text(),
            search_method=agent_result.agent,
            screen_context=agent_result.final_ui,
            plan=plan,
        )

    return VoiceResult(
        message=(
            'Try: “Play Inception”, “Search for Dune”, “Open Netflix”, '
            '“Press down”, or “Type batman”.'
        ),
        action="unknown",
    )


def _parsed_payload(command: VoiceCommand) -> dict[str, Any]:
    return {
        "action": command.action,
        "app": command.app,
        "title": command.title,
        "key": command.key,
        "keys": command.keys,
        "text": command.text,
    }


def _fast_response(command: VoiceCommand, result: VoiceResult) -> dict[str, Any]:
    return {
        "mode": "fast",
        "success": True,
        "message": result.message,
        "log": None,
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
        "parsed": _parsed_payload(command),
        "agent": llm_provider() or "rules",
    }


def _search_response(command: VoiceCommand, result: VoiceResult) -> dict[str, Any]:
    return {
        "mode": "play" if result.action == "play_media" else "search",
        "success": result.action == "play_media",
        "message": result.message,
        "log": result.search_steps,
        "action": result.action,
        "app": result.app,
        "title": result.title,
        "search_query": result.search_query,
        "search_method": result.search_method,
        "search_steps": result.search_steps,
        "screen_context": result.screen_context,
        "screen_trail": None,
        "plan": result.plan,
        "providers": result.providers,
        "parsed": _parsed_payload(command),
        "agent": llm_provider() or "rules",
    }


async def handle_voice_command(session: RokuEcp2Client, text: str) -> dict[str, Any]:
    """Parse command, run keys/apps instantly, or type exact words in Roku Search."""
    command = await parse_command(text)

    if command.action in FAST_ACTIONS:
        result = await execute_command(session, command)
        return _fast_response(command, result)

    if command.action in SEARCH_ACTIONS and command.title:
        result = await execute_command(session, command)
        return _search_response(command, result)

    result = await execute_command(session, command)
    if result.action == "unknown":
        return {
            "mode": "fast",
            "success": False,
            "message": result.message,
            "log": None,
            "action": "unknown",
            "parsed": _parsed_payload(command),
            "agent": llm_provider() or "rules",
        }
    return _fast_response(command, result)