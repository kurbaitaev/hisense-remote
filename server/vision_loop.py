"""Multi-step see → act loop using phone camera frames."""

from __future__ import annotations

from typing import Any

from server.roku_ecp2 import RokuEcp2Client
from server.tv_ui_reader import read_ui
from server.vision_agent import vision_act


async def run_vision_steps(
    session: RokuEcp2Client,
    frames: list[bytes],
    *,
    goal: str,
    mime_type: str = "image/jpeg",
) -> dict[str, Any]:
    """Run vision+act for each frame in order (user snaps between steps)."""
    log: list[dict[str, Any]] = []

    for index, frame in enumerate(frames, start=1):
        ui = await read_ui(session, include_device=False)
        ecp_context = {
            "app_name": ui.app_name,
            "app_id": ui.app_id,
            "screen": ui.screen.value,
            "summary": ui.summary(),
            "player_state": ui.player.state if ui.player else "none",
        }
        step = await vision_act(
            session,
            frame,
            goal=goal,
            ecp_context=ecp_context,
            mime_type=mime_type,
        )
        step["step"] = index
        log.append(step)
        if step.get("goal_status") == "done":
            break

    last = log[-1] if log else {}
    return {
        "goal": goal,
        "steps": log,
        "steps_taken": len(log),
        "goal_status": last.get("goal_status", "unknown"),
        "message": last.get("message", "No steps run."),
        "screen_summary": last.get("screen_summary", ""),
    }