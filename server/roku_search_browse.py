"""Roku search APIs — /search/browse (universal) and /launch/?search= (per-app)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from server.apps_config import get_installed_apps, get_paramount_profile_down_presses
from server.roku_ecp2 import APP_MAP
from server.tv_ui_reader import UiScreen

if TYPE_CHECKING:
    from server.roku_ecp2 import RokuEcp2Client
    from server.play_orchestrator import PlayPlan
    from server.smart_agent import AgentResult, AgentStep

# Spoken aliases → our app keys (from julianh2o/RokuAlexaLambdaSkill)
CHANNEL_ALIASES: dict[str, str] = {
    "plex": "plex",
    "hulu": "hulu",
    "pandora": "pandora",
    "amazon": "prime",
    "amazon video": "prime",
    "prime": "prime",
    "prime video": "prime",
    "netflix": "netflix",
    "youtube": "youtube",
    "disney": "disney",
    "disney+": "disney",
    "disney plus": "disney",
    "paramount": "paramount",
    "paramount+": "paramount",
    "paramount plus": "paramount",
}

EXTRA_APP_IDS: dict[str, str] = {
    "plex": "13535",
    "pandora": "28",
}


def resolve_app_id(app_key: str) -> str | None:
    key = app_key.strip().lower()
    key = CHANNEL_ALIASES.get(key, key)
    if key in APP_MAP:
        return APP_MAP[key]
    return EXTRA_APP_IDS.get(key)


def provider_ids_for_apps(app_keys: list[str] | None = None) -> list[str]:
    keys = app_keys or list(get_installed_apps())
    ids: list[str] = []
    for key in keys:
        app_id = resolve_app_id(key)
        if app_id and app_id not in ids:
            ids.append(app_id)
    return ids


async def http_search_browse(
    host: str,
    title: str,
    *,
    provider_ids: list[str] | None = None,
    launch: bool = True,
    match_any: bool = True,
    timeout: float = 10.0,
) -> bool:
    """Universal Roku search UI — best when no specific app is chosen."""
    ids = provider_ids or provider_ids_for_apps()
    if not ids:
        return False
    ids_param = "%2c".join(ids)
    path = (
        f"/search/browse?title={quote(title)}"
        f"&provider-id={ids_param}"
        f"&launch={'true' if launch else 'false'}"
        f"&match-any={'true' if match_any else 'false'}"
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"http://{host}:8060{path}")
        return resp.status_code < 400
    except httpx.HTTPError:
        return False


def _want_app_id(plan: PlayPlan) -> str | None:
    if not plan.app:
        return None
    return resolve_app_id(plan.app)


async def _enter_paramount_profile(session: RokuEcp2Client, steps: list) -> None:
    from server.smart_agent import AgentStep
    from server.tv_ui_reader import _diff_snapshots, read_ui

    downs = get_paramount_profile_down_presses()
    before = await read_ui(session)
    for _ in range(downs):
        await session._send_key_raw("Down")
        await asyncio.sleep(0.6)
    await session._send_key_raw("Select")
    await asyncio.sleep(3.0)
    after = await read_ui(session)
    steps.append(
        AgentStep(
            step=len(steps) + 1,
            reasoning="Paramount Who's Watching — OK on top profile (Kids is below)",
            action="key",
            detail=f"Down×{downs}, OK",
            before_summary=before.summary(),
            after_summary=after.summary(),
            delta=_diff_snapshots(before, after),
            goal_progress=45,
        )
    )


async def _wait_for_play(session: RokuEcp2Client, *, seconds: float = 18.0):
    from server.tv_ui_reader import read_ui

    deadline = asyncio.get_event_loop().time() + seconds
    ui = await read_ui(session)
    while asyncio.get_event_loop().time() < deadline:
        if ui.player.is_confirmed_playback:
            return ui
        await asyncio.sleep(1.5)
        ui = await read_ui(session)
    return ui


async def _append_key_step(steps: list, *, st, reasoning: str, detail: str, progress: int) -> None:
    from server.smart_agent import AgentStep

    steps.append(
        AgentStep(
            step=len(steps) + 1,
            reasoning=reasoning,
            action="key",
            detail=detail,
            before_summary=st.before.summary(),
            after_summary=st.after.summary(),
            delta=st.delta,
            goal_progress=progress,
        )
    )


def _on_paramount_home(ui) -> bool:
    """Paramount home carousel — OK here clicks random featured tiles, not the movie."""
    return (
        ui.app_id == APP_MAP.get("paramount")
        and ui.screen == UiScreen.PARAMOUNT
        and not ui.player.is_confirmed_playback
    )


async def _open_paramount_search_and_type(
    session: RokuEcp2Client,
    plan: PlayPlan,
    steps: list,
) -> None:
    """Open Paramount's search UI and type the title (deep-link search is unreliable on this TV)."""
    from server.smart_agent import AgentStep
    from server.tv_ui_reader import press_and_read, read_ui

    query = plan.search_text
    ui = await read_ui(session)

    if ui.screen in (UiScreen.ROKU_SEARCH_TYPING, UiScreen.ROKU_SEARCH_RESULTS):
        if not ui.textedit.text.strip():
            await session.send_text(query)
            steps.append(
                AgentStep(
                    step=len(steps) + 1,
                    reasoning="Type into Roku universal search",
                    action="type",
                    detail=query,
                    before_summary=ui.summary(),
                    after_summary=ui.summary(),
                    delta=[f'typed "{query}"'],
                    goal_progress=48,
                )
            )
            await asyncio.sleep(2.0)
        return

    _, _, st = await press_and_read(session, "Search", intent="Open Paramount search")
    await _append_key_step(
        steps,
        st=st,
        reasoning="Search key — open Paramount in-app search (not home carousel)",
        detail="search",
        progress=48,
    )
    await asyncio.sleep(2.5)

    before = await read_ui(session)
    await session.send_text(query)
    await asyncio.sleep(4.5)
    after = await read_ui(session)
    steps.append(
        AgentStep(
            step=len(steps) + 1,
            reasoning=f'Type "{query}" into Paramount search',
            action="type",
            detail=query,
            before_summary=before.summary(),
            after_summary=after.summary(),
            delta=[f'typed "{query}"'],
            goal_progress=50,
        )
    )


async def _focus_search_results_row(
    session: RokuEcp2Client,
    plan: PlayPlan,
    steps: list,
) -> None:
    """Move focus from the search box to the results row."""
    from server.tv_ui_reader import press_and_read, read_ui

    ui = await read_ui(session)
    if ui.screen in (UiScreen.ROKU_SEARCH_TYPING, UiScreen.ROKU_SEARCH_RESULTS):
        await _leave_search_field_if_needed(session, steps)
        return

    if ui.screen in (UiScreen.PARAMOUNT, UiScreen.PARAMOUNT_INFERRED_SEARCH):
        _, _, st = await press_and_read(
            session,
            "Down",
            intent="From search box down to results row",
        )
        await _append_key_step(
            steps,
            st=st,
            reasoning="Down — focus search results (safe inside search UI)",
            detail="down",
            progress=54,
        )
        await asyncio.sleep(0.8)


async def _leave_search_field_if_needed(
    session: RokuEcp2Client,
    steps: list,
    *,
    max_downs: int = 6,
) -> None:
    """Only press Down while the cursor is still in a search text field."""
    from server.tv_ui_reader import press_and_read, read_ui

    ui = await read_ui(session)
    downs = 0
    while ui.textedit.in_field and downs < max_downs:
        _, _, st = await press_and_read(session, "Down", intent="Leave search field")
        await _append_key_step(
            steps,
            st=st,
            reasoning="Down — leave search field for results",
            detail="down",
            progress=52,
        )
        downs += 1
        await asyncio.sleep(0.75)
        ui = await read_ui(session)


async def _confirm_watch_play(
    session: RokuEcp2Client,
    plan: PlayPlan,
    steps: list,
    *,
    progress_base: int,
) -> None:
    """OK through detail → Watch → Play when needed."""
    from server.tv_ui_reader import press_and_read, read_ui

    title = plan.title
    app = plan.app

    _, _, st = await press_and_read(session, "Select", intent=f'OK — "{title}"')
    await _append_key_step(
        steps,
        st=st,
        reasoning=f'Select "{title}"',
        detail="ok",
        progress=progress_base,
    )
    await asyncio.sleep(2.5)

    if app == "paramount":
        _, _, st = await press_and_read(session, "Select", intent="OK — Watch")
        await _append_key_step(
            steps,
            st=st,
            reasoning="Paramount: OK on Watch",
            detail="ok",
            progress=progress_base + 15,
        )
        await asyncio.sleep(3.0)

    ui = await read_ui(session)
    if not ui.player.is_confirmed_playback:
        _, _, st = await press_and_read(session, "Play", intent="Start playback")
        await _append_key_step(
            steps,
            st=st,
            reasoning="Press Play to start",
            detail="play",
            progress=progress_base + 25,
        )
        await asyncio.sleep(2.5)


async def _play_from_app_search(
    session: RokuEcp2Client,
    plan: PlayPlan,
    steps: list,
) -> None:
    """Pick the search result and start playback (Paramount/Netflix deep-link flow).

    Paramount deep-link search already highlights the best match on top.
    Pressing Down moves to the next row (often the wrong title) — never do that blindly.
    """
    from server.tv_ui_reader import press_and_read, read_ui

    app = plan.app
    if app not in ("paramount", "netflix"):
        return

    if app == "paramount":
        ui = await read_ui(session)
        if ui.screen not in (UiScreen.ROKU_SEARCH_TYPING, UiScreen.ROKU_SEARCH_RESULTS):
            await _open_paramount_search_and_type(session, plan, steps)
        await _focus_search_results_row(session, plan, steps)

    max_candidates = 5 if app == "paramount" else 1
    for candidate in range(max_candidates):
        if candidate > 0:
            _, _, st = await press_and_read(
                session,
                "Right",
                intent=f"Try next search result (#{candidate + 1})",
            )
            await _append_key_step(
                steps,
                st=st,
                reasoning=f"Wrong title — try next result (→ #{candidate + 1})",
                detail="right",
                progress=55 + candidate * 5,
            )
            await asyncio.sleep(0.7)

        await _confirm_watch_play(
            session,
            plan,
            steps,
            progress_base=60 + candidate * 5,
        )
        ui = await _wait_for_play(session, seconds=12.0)
        if ui.player.is_confirmed_playback:
            return

        if candidate < max_candidates - 1:
            _, _, st = await press_and_read(session, "Back", intent="Back to search results")
            await _append_key_step(
                steps,
                st=st,
                reasoning="Not playing — back to results grid",
                detail="back",
                progress=58 + candidate * 5,
            )
            await asyncio.sleep(1.2)
            ui = await read_ui(session)
            if ui.textedit.in_field:
                await _leave_search_field_if_needed(session, steps)


async def _nudge_playback(session: RokuEcp2Client, steps: list) -> None:
    from server.tv_ui_reader import press_and_read, read_ui

    ui = await read_ui(session)
    if ui.textedit.in_field:
        return

    if not ui.player.is_confirmed_playback:
        _, _, st = await press_and_read(session, "Select", intent="OK on highlighted item")
        await _append_key_step(
            steps,
            st=st,
            reasoning="Select highlighted result",
            detail="ok",
            progress=75,
        )
        await asyncio.sleep(2.5)
        ui = await read_ui(session)

    if not ui.player.is_confirmed_playback and not ui.textedit.in_field:
        _, _, st = await press_and_read(session, "Play", intent="Start playback")
        await _append_key_step(
            steps,
            st=st,
            reasoning="Press Play",
            detail="play",
            progress=90,
        )


async def play_via_search_browse(
    session: RokuEcp2Client,
    plan: PlayPlan,
) -> AgentResult:
    """Fast play: per-app launch search, or universal search/browse if no app pinned."""
    from server.smart_agent import AgentResult, AgentStep
    from server.tv_ui_reader import _diff_snapshots, read_ui

    title = plan.search_text
    goal = f'Watch "{plan.title}"' + (f" on {plan.app}" if plan.app else "")
    steps: list[AgentStep] = []
    want_id = _want_app_id(plan)

    await session.go_home()
    await asyncio.sleep(2.0)
    before = await read_ui(session)

    if plan.app == "paramount":
        await session.launch_app("paramount")
        ok = True
        method = "paramount_in_app_search"
        detail = f'open Paramount → search "{title}"'
        await asyncio.sleep(5.0)
    elif plan.app:
        ok = await session._deep_link_search(plan.app, title)
        method = "launch_search"
        detail = f'{plan.app} launch ?search="{title}"'
        await asyncio.sleep(9.0)
    else:
        ids = provider_ids_for_apps(list(get_installed_apps()))
        ok = await http_search_browse(session.host, title, provider_ids=ids)
        method = "search_browse"
        detail = f'browse "{title}" providers={ids}'
        await asyncio.sleep(9.0)

    after = await read_ui(session)
    steps.append(
        AgentStep(
            step=1,
            reasoning="Open search via Roku API (not blind key mash)",
            action=method,
            detail=detail,
            before_summary=before.summary(),
            after_summary=after.summary(),
            delta=_diff_snapshots(before, after),
            goal_progress=30 if ok else 5,
        )
    )

    if not ok:
        return AgentResult(
            goal=goal,
            success=False,
            message=f"{method} request failed.",
            steps=steps,
            plan=plan.to_dict(),
            agent=method,
        )

    ui = after
    if want_id and ui.app_id != want_id:
        await asyncio.sleep(4.0)
        ui = await read_ui(session)

    if plan.app == "paramount" and ui.app_id == "31440" and not ui.player.is_confirmed_playback:
        await _enter_paramount_profile(session, steps)
        ui = await read_ui(session)

    if (
        plan.app in ("paramount", "netflix")
        and not ui.player.is_confirmed_playback
    ):
        await _play_from_app_search(session, plan, steps)
        ui = await read_ui(session)

    if not plan.app and ui.textedit.in_field and not ui.textedit.text.strip():
        await session.send_text(title)
        await asyncio.sleep(1.5)
        ui = await read_ui(session)
        steps.append(
            AgentStep(
                step=len(steps) + 1,
                reasoning="Type search query into Roku universal search",
                action="type",
                detail=title,
                before_summary=after.summary(),
                after_summary=ui.summary(),
                delta=[f'typed "{title}"'],
                goal_progress=50,
            )
        )

    ui = await _wait_for_play(session, seconds=20.0)
    if not ui.player.is_confirmed_playback:
        await _nudge_playback(session, steps)
        ui = await _wait_for_play(session, seconds=12.0)

    success = ui.player.is_confirmed_playback
    return AgentResult(
        goal=goal,
        success=success,
        message=(
            f"{'Now playing' if success else 'Opened app but playback not confirmed'} "
            f"via {method} — {ui.summary()}."
        ),
        steps=steps,
        final_ui={
            "summary": ui.summary(),
            "player_state": ui.player.state,
            "app_name": ui.app_name,
            "app_id": ui.app_id,
        },
        plan=plan.to_dict(),
        agent=method,
    )