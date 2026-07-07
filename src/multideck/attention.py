"""Attention engine — turns the agent_state store into an operator signal.

``agent_state`` receives per-session lifecycle states from agent hooks
(Claude Code hooks, Codex notify). This module is the read side: it polls
the store, applies staleness (a "working" record from yesterday is not
working), maps session cwds onto configured project names, sorts by how
urgently each session needs the user, and reports *transitions* so
renderers (window badges, taskbar flashes, toasts, ntfy pushes — PR-B/C)
can fire exactly once per state change.

Pure logic: no platform calls, no I/O beyond agent_state reads, injectable
clock — everything here is unit-testable with a fake store and fake time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from multideck import agent_state

if TYPE_CHECKING:
    from collections.abc import Callable

# A stale record stops meaning what it says: an agent can't be "working" for
# half an hour without a state write (hooks fire every turn), and a
# needs-input prompt older than an hour has usually been answered in the
# window itself. Promoted from cli/session_picker.py, which now shares these.
STALENESS_S: dict[str, float] = {
    agent_state.WORKING: 1800.0,
    agent_state.NEEDS_INPUT: 3600.0,
}

# Sort order: the more a state needs the user, the earlier it sorts.
_URGENCY: dict[str, int] = {
    agent_state.NEEDS_INPUT: 0,
    agent_state.ERROR: 1,
    agent_state.DONE: 2,
    agent_state.WORKING: 3,
    agent_state.IDLE: 4,
}

# Push-style renderers must not re-fire while a session sits in the same
# state across polls; transitions() only reports changes, and this debounce
# additionally suppresses rapid flapping back into the same state.
DEBOUNCE_S = 300.0


@dataclass
class SessionView:
    """One session as the user should see it right now."""

    name: str  # configured project name, or the cwd leaf as fallback
    cwd: str  # normalized cwd (the store key)
    state: str  # effective state (staleness applied)
    ts: float  # when the record was written
    age_s: float  # seconds since ts, at poll time


@dataclass
class Transition:
    """A session entering a new effective state since the previous poll."""

    view: SessionView
    prev_state: str | None  # None = session first seen by this engine


def name_map_from_projects(projects: list[tuple[str, str]]) -> dict[str, str]:
    """Build the {normalized cwd: display name} map from (name, path) pairs.

    Callers derive the pairs from config: the project's title (or path leaf)
    and its path. Kept as plain tuples so this module needs no config import.
    """
    return {agent_state.norm_cwd(path): name for name, path in projects if path}


def _leaf(cwd: str) -> str:
    return cwd.rsplit("/", 1)[-1] if "/" in cwd else cwd


class AttentionEngine:
    def __init__(
        self,
        name_by_cwd: dict[str, str] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._name_by_cwd = dict(name_by_cwd or {})
        self._now = now
        self._last_state: dict[str, str] = {}
        self._last_fired: dict[tuple[str, str], float] = {}

    def poll(self) -> list[SessionView]:
        """Read the store and return the current views, most-urgent first."""
        now = self._now()
        views: list[SessionView] = []
        for rec in agent_state.all_states():
            raw_state = rec.get("state")
            raw_cwd = rec.get("cwd")
            if not isinstance(raw_state, str) or not isinstance(raw_cwd, str):
                continue
            ts_raw = rec.get("ts", 0)
            ts = (
                float(ts_raw)
                if isinstance(ts_raw, (int, float)) and not isinstance(ts_raw, bool)
                else 0.0
            )
            age = max(0.0, now - ts)
            state = raw_state
            stale_after = STALENESS_S.get(state)
            if stale_after is not None and age > stale_after:
                state = agent_state.IDLE
            views.append(
                SessionView(
                    name=self._name_by_cwd.get(raw_cwd, _leaf(raw_cwd)),
                    cwd=raw_cwd,
                    state=state,
                    ts=ts,
                    age_s=age,
                )
            )
        views.sort(key=lambda v: (_URGENCY.get(v.state, 99), -v.ts))
        return views

    def transitions(self, views: list[SessionView]) -> list[Transition]:
        """Diff ``views`` against the previous poll; report entered states.

        Call once per poll with that poll's views. Sessions that vanished
        from the store are forgotten (their next appearance is a fresh
        transition again).
        """
        out: list[Transition] = []
        seen: dict[str, str] = {}
        for v in views:
            seen[v.cwd] = v.state
            prev = self._last_state.get(v.cwd)
            if prev != v.state:
                out.append(Transition(view=v, prev_state=prev))
        self._last_state = seen
        return out

    def should_fire(self, cwd: str, state: str) -> bool:
        """Debounce gate for push renderers (toast/ntfy): at most one firing
        per (session, state) every DEBOUNCE_S seconds."""
        key = (cwd, state)
        now = self._now()
        last = self._last_fired.get(key)
        if last is not None and (now - last) < DEBOUNCE_S:
            return False
        self._last_fired[key] = now
        return True
