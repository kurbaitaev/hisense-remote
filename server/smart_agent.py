"""Observe → reason → act → verify TV control loop.

Replaces blind key recipes. The LLM sees ECP state after every step and picks
the next single action toward the goal.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from server.apps_config import get_installed_apps, get_paramount_profile_down_presses, load_config
from server.llm import llm_available, llm_provider, parse_voice_json
from server.movie_lookup import lookup_media
from server.play_orchestrator import PlayPlan, build_play_plan
from server.roku_ecp2 import APP_MAP, KEY_MAP, RokuEcp2Client, RokuEcp2Error
from server.tv_ui_reader import TvUiSnapshot, UiScreen, _diff_snapshots, read_ui, press_and_read

ActionKind = Literal[
    "key",
    "type",
    "launch_app",
    "deep_link",
    "search_browse",
    "go_home",
    "wait",
    "done",
    "abort",
]

MAX_STEPS = 28

ALLOWED_KEYS = frozenset({
    "up", "down", "left", "right", "ok", "back", "home",
    "play", "pause", "rewind", "fast_forward",
    "volume_up", "volume_down", "mute",
    "channel_up", "channel_down", "search", "power",
})


@dataclass
class AgentStep:
    step: int
    reasoning: str
    action: str
    detail: str
    before_summary: str
    after_summary: str
    delta: list[str]
    goal_progress: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "reasoning": self.reasoning,
            "action": self.action,
            "detail": self.detail,
            "before": self.before_summary,
            "after": self.after_summary,
            "delta": self.delta,
            "goal_progress": self.goal_progress,
        }


@dataclass
class AgentResult:
    goal: str
    success: bool
    message: str
    steps: list[AgentStep] = field(default_factory=list)
    final_ui: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    agent: str = "rules"

    def log_text(self) -> str:
        lines = [self.message]
        for s in self.steps:
            lines.append(
                f"Step {s.step}: {s.reasoning}\n"
                f"  → {s.action}: {s.detail}\n"
                f"  {s.before_summary} ⇒ {s.after_summary}"
            )
            if s.delta:
                lines.append(f"  Δ {', '.join(s.delta)}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "success": self.success,
            "message": self.message,
            "steps": [s.to_dict() for s in self.steps],
            "final_ui": self.final_ui,
            "plan": self.plan,
            "agent": self.agent,
            "log": self.log_text(),
        }


def _observation_dict(ui: TvUiSnapshot) -> dict[str, Any]:
    return {
        "summary": ui.summary(),
        "screen": ui.screen.value,
        "app_name": ui.app_name,
        "app_id": ui.app_id,
        "player_state": ui.player.state,
        "is_playing": ui.player.is_confirmed_playback,
        "player_warming": ui.player.is_warming_up,
        "search_text": ui.textedit.text,
        "in_search_field": ui.textedit.in_field,
        "readable": ui.readable,
        "blind_spots": ui.blind_spots,
        "inference_note": ui.inference_note,
    }


def _goal_achieved(ui: TvUiSnapshot, plan: PlayPlan | None, goal: str) -> bool:
    if ui.player.is_confirmed_playback:
        return True
    if plan and plan.intent == "play_movie" and ui.screen == UiScreen.PLAYING:
        return ui.player.is_confirmed_playback
    return False


def _history_text(steps: list[AgentStep]) -> str:
    if not steps:
        return "(no actions yet)"
    lines = []
    for s in steps[-8:]:
        lines.append(
            f"- Step {s.step}: {s.action} {s.detail} → {s.after_summary} "
            f"(Δ {', '.join(s.delta) if s.delta else 'none'})"
        )
    return "\n".join(lines)


def _tv_hints() -> str:
    cfg = load_config()
    paramount_downs = get_paramount_profile_down_presses()
    installed = ", ".join(get_installed_apps()) or "unknown"
    return (
        f"Installed apps: {installed}.\n"
        f"Paramount profiles are VERTICAL: top = adult (user), below = Kids. "
        f"profile_down_presses={paramount_downs}: 0 = OK on top profile. "
        f"NEVER press Down on Who's Watching — Down selects Kids.\n"
        "Inside Netflix/Paramount/Prime you CANNOT see menus, focus, or profile names — infer carefully.\n"
        "Roku universal Search: search bar text and in-field focus ARE visible.\n"
        "Success for play goals: media player state becomes play/buffer/pause."
    )


async def _decide(
    *,
    goal: str,
    plan: PlayPlan | None,
    observation: dict[str, Any],
    steps: list[AgentStep],
) -> dict[str, Any]:
    plan_text = plan.summary() if plan else goal
    prompt = f"""You are an autonomous Roku TV agent. Pick ONE next action based on observations.

GOAL: {goal}
PLAN: {plan_text}

{_tv_hints()}

RECENT HISTORY:
{_history_text(steps)}

CURRENT OBSERVATION (from TV API — trust player/app/search fields):
{json.dumps(observation, indent=2)}

Return JSON only:
{{
  "reasoning": "one sentence",
  "action": "key|type|launch_app|deep_link|search_browse|go_home|wait|done|abort",
  "key": "up|down|left|right|ok|back|home|play|pause|search|...|null",
  "text": "string or null",
  "app": "netflix|paramount|prime|youtube|disney|hulu|null",
  "search_query": "string or null",
  "wait_seconds": 2,
  "goal_progress": 0,
  "confidence": 0.0
}}

Strategy:
- Prefer search_browse for play goals (one Roku API: search + launch)
- Else deep_link to open app+search on netflix/paramount
- After deep_link into Paramount: if player is close/none, likely Who's Watching — press OK only (adult is on TOP)
- NEVER press Down on Paramount profile picker — Down moves to Kids below
- If in Roku Search with wrong/empty bar, type the search_query
- If search typed and not in field, Down then OK to select
- If playing (player play/buffer/pause), action=done
- If stuck repeating same observation 3+ times, try Back or go_home then retry
- wait 2-4s after launch/deep_link before keys
- abort only if truly impossible
"""
    parsed = await parse_voice_json(prompt)
    if not parsed:
        return _fallback_decide(goal=goal, plan=plan, observation=observation, steps=steps)
    return parsed


def _fallback_decide(
    *,
    goal: str,
    plan: PlayPlan | None,
    observation: dict[str, Any],
    steps: list[AgentStep],
) -> dict[str, Any]:
    """Rule-based backup when LLM unavailable."""
    if observation.get("is_playing"):
        return {
            "reasoning": "Video is playing.",
            "action": "done",
            "goal_progress": 100,
            "confidence": 0.9,
        }

    if plan and len(steps) == 0:
        return {
            "reasoning": f"search/browse for {plan.search_text!r}.",
            "action": "search_browse",
            "app": plan.app,
            "search_query": plan.search_text,
            "wait_seconds": 8,
            "goal_progress": 20,
            "confidence": 0.85,
        }

    last_actions = [s.action for s in steps[-3:]]
    if last_actions.count("key") >= 3 and observation.get("player_state") == "close":
        return {
            "reasoning": "Stuck without playback — try OK.",
            "action": "key",
            "key": "ok",
            "goal_progress": 40,
            "confidence": 0.4,
        }

    if observation.get("in_search_field") and plan:
        return {
            "reasoning": "Type into Roku search field.",
            "action": "type",
            "text": plan.search_text,
            "goal_progress": 50,
            "confidence": 0.6,
        }

    return {
        "reasoning": "Default navigation down.",
        "action": "key",
        "key": "down",
        "goal_progress": 30,
        "confidence": 0.3,
    }


def _normalize_decision(raw: dict[str, Any]) -> dict[str, Any]:
    action = str(raw.get("action", "wait")).lower()
    if action not in (
        "key", "type", "launch_app", "deep_link", "search_browse",
        "go_home", "wait", "done", "abort",
    ):
        action = "wait"
    key = str(raw.get("key") or "").lower().replace(" ", "_")
    if key in ("select", "enter"):
        key = "ok"
    if key and key not in ALLOWED_KEYS:
        key = ""
    try:
        wait_seconds = max(0.5, min(12.0, float(raw.get("wait_seconds", 2))))
    except (TypeError, ValueError):
        wait_seconds = 2.0
    try:
        progress = int(raw.get("goal_progress", 0))
    except (TypeError, ValueError):
        progress = 0
    return {
        "reasoning": str(raw.get("reasoning", "")).strip() or "Continuing toward goal.",
        "action": action,
        "key": key,
        "text": (raw.get("text") or "").strip() or None,
        "app": (raw.get("app") or "").strip().lower() or None,
        "search_query": (raw.get("search_query") or "").strip() or None,
        "wait_seconds": wait_seconds,
        "goal_progress": max(0, min(100, progress)),
        "confidence": float(raw.get("confidence", 0.5) or 0.5),
    }


async def _execute_decision(
    session: RokuEcp2Client,
    decision: dict[str, Any],
    plan: PlayPlan | None,
) -> tuple[str, str, TvUiSnapshot, TvUiSnapshot, list[str]]:
    action = decision["action"]
    before = await read_ui(session)

    if action == "wait":
        await asyncio.sleep(decision["wait_seconds"])
        after = await read_ui(session)
        detail = f"wait {decision['wait_seconds']}s"
        return action, detail, before, after, _diff_snapshots(before, after)

    if action == "go_home":
        await session.go_home()
        await asyncio.sleep(1.0)
        after = await read_ui(session)
        return action, "go_home", before, after, _diff_snapshots(before, after)

    if action == "launch_app" and decision.get("app"):
        await session.launch_app(decision["app"])
        await asyncio.sleep(decision["wait_seconds"])
        after = await read_ui(session)
        return action, decision["app"], before, after, _diff_snapshots(before, after)

    if action == "search_browse":
        query = decision.get("search_query") or (plan.search_text if plan else None)
        if not query:
            raise RokuEcp2Error("search_browse missing query")
        app_keys = [decision["app"]] if decision.get("app") else (
            [plan.app] if plan and plan.app else None
        )
        ok = await session.search_browse(query, app_keys=app_keys)
        if not ok:
            raise RokuEcp2Error("search/browse failed")
        await asyncio.sleep(decision["wait_seconds"])
        after = await read_ui(session)
        detail = f'browse "{query}"' + (f" on {app_keys[0]}" if app_keys else "")
        return action, detail, before, after, _diff_snapshots(before, after)

    if action == "deep_link":
        app = decision.get("app") or (plan.app if plan else None)
        query = decision.get("search_query") or (plan.search_text if plan else None)
        if not app or not query:
            raise RokuEcp2Error("deep_link missing app or search_query")
        ok = await session._deep_link_search(app, query)
        if not ok:
            raise RokuEcp2Error(f"deep_link failed for {app}")
        await asyncio.sleep(decision["wait_seconds"])
        after = await read_ui(session)
        return action, f"{app} search {query!r}", before, after, _diff_snapshots(before, after)

    if action == "type" and decision.get("text"):
        await session.send_text(decision["text"])
        await asyncio.sleep(1.2)
        after = await read_ui(session)
        return action, decision["text"], before, after, _diff_snapshots(before, after)

    if action == "key" and decision.get("key"):
        key = decision["key"]
        roku_key = KEY_MAP.get(key, key)
        _, after, step = await press_and_read(session, roku_key, intent=decision["reasoning"])
        return action, key, step.before, step.after, step.delta

    after = before
    return action, "noop", before, after, []


async def run_agent(
    session: RokuEcp2Client,
    goal: str,
    *,
    plan: PlayPlan | None = None,
) -> AgentResult:
    """Run the observe-reason-act loop until done, abort, or step limit."""
    if not goal.strip():
        return AgentResult(goal="", success=False, message="Empty goal.", agent=llm_provider() or "rules")

    steps: list[AgentStep] = []
    agent_name = llm_provider() or "rules"
    start = time.monotonic()

    for step_num in range(1, MAX_STEPS + 1):
        ui = await read_ui(session)
        obs = _observation_dict(ui)

        if _goal_achieved(ui, plan, goal):
            return AgentResult(
                goal=goal,
                success=True,
                message=f"Goal achieved in {step_num - 1} steps ({ui.summary()}).",
                steps=steps,
                final_ui=obs,
                plan=plan.to_dict() if plan else None,
                agent=agent_name,
            )

        if not llm_available() and step_num > 12:
            return AgentResult(
                goal=goal,
                success=False,
                message="Step limit reached without playback (add GROQ_API_KEY or GEMINI_API_KEY for smarter control).",
                steps=steps,
                final_ui=obs,
                plan=plan.to_dict() if plan else None,
                agent=agent_name,
            )

        decision = _normalize_decision(
            await _decide(goal=goal, plan=plan, observation=obs, steps=steps)
            if llm_available()
            else _fallback_decide(goal=goal, plan=plan, observation=obs, steps=steps)
        )

        if decision["action"] == "done":
            ui2 = await read_ui(session)
            playing = ui2.player.is_confirmed_playback
            return AgentResult(
                goal=goal,
                success=playing,
                message="Agent marked done." + (" Playing." if playing else " Not confirmed playing."),
                steps=steps,
                final_ui=_observation_dict(ui2),
                plan=plan.to_dict() if plan else None,
                agent=agent_name,
            )

        if decision["action"] == "abort":
            return AgentResult(
                goal=goal,
                success=False,
                message=f"Agent aborted: {decision['reasoning']}",
                steps=steps,
                final_ui=obs,
                plan=plan.to_dict() if plan else None,
                agent=agent_name,
            )

        try:
            action, detail, before, after, delta = await _execute_decision(
                session, decision, plan,
            )
        except RokuEcp2Error as exc:
            return AgentResult(
                goal=goal,
                success=False,
                message=f"Stopped at step {step_num}: {exc}",
                steps=steps,
                final_ui=obs,
                plan=plan.to_dict() if plan else None,
                agent=agent_name,
            )

        steps.append(
            AgentStep(
                step=step_num,
                reasoning=decision["reasoning"],
                action=action,
                detail=detail,
                before_summary=before.summary(),
                after_summary=after.summary(),
                delta=delta,
                goal_progress=decision["goal_progress"],
            )
        )

        if time.monotonic() - start > 120:
            break

    ui = await read_ui(session)
    return AgentResult(
        goal=goal,
        success=ui.player.is_confirmed_playback,
        message="Step limit reached." + (" Playing." if ui.player.is_confirmed_playback else ""),
        steps=steps,
        final_ui=_observation_dict(ui),
        plan=plan.to_dict() if plan else None,
        agent=agent_name,
    )


async def run_play_goal(
    session: RokuEcp2Client,
    *,
    heard: str,
    title: str,
    app: str | None = None,
) -> AgentResult:
    """Smart play: search/browse first, then agent loop if needed."""
    from server.roku_search_browse import play_via_search_browse

    media = await lookup_media(title)
    plan = build_play_plan(
        heard=heard,
        requested_title=title,
        requested_app=app,
        media=media,
    )
    goal = f'Watch "{plan.title}"' + (f" on {plan.app}" if plan.app else "")

    browse_result = await play_via_search_browse(session, plan)
    if browse_result.success:
        return browse_result

    agent_result = await run_agent(session, goal, plan=plan)
    if agent_result.success:
        return agent_result

    browse_result.message = (
        f"{browse_result.message}\n\nFallback agent: {agent_result.message}"
    )
    browse_result.steps.extend(agent_result.steps)
    browse_result.success = agent_result.success
    browse_result.final_ui = agent_result.final_ui or browse_result.final_ui
    browse_result.agent = f"search_browse+{agent_result.agent}"
    return browse_result