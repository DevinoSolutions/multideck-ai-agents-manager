"""Attention engine + renderers — turns the agent_state store into operator signals.

``agent_state`` receives per-session lifecycle states from agent hooks
(Claude Code hooks, Codex notify). This module is the read side: the engine
polls the store, applies staleness (a "working" record from yesterday is not
working), maps session cwds onto configured project names, sorts by how
urgently each session needs the user, and reports *transitions*. Renderers
turn those into signals: window-title badges and taskbar flashes (via the
platform's attention primitives), Windows toasts (optional winotify extra),
and ntfy pushes (stdlib urllib, topic from MULTIDECK_NTFY_TOPIC).

The engine is pure logic (fake store + fake clock in tests); renderers take
a Platform instance and are tested against recording fakes. A renderer that
raises a non-environmental error crashes the loop on purpose — the loudness
doctrine: a broken daemon must page (log + stale heartbeat in `status`),
never limp silently.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from multideck import agent_state
from multideck.log import get_logger
from multideck.titles import make_title, parse_title

if TYPE_CHECKING:
    from collections.abc import Callable

    from multideck.platform import Platform

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


# --- Renderers ---------------------------------------------------------------

# States that warrant an interruption (flash/toast/ntfy). done is deliberately
# badge-only: "your turn" is worth a glance, not a page.
PUSH_STATES = frozenset({agent_state.NEEDS_INPUT, agent_state.ERROR})


class Renderer(Protocol):
    def render(
        self, views: list[SessionView], transitions: list[Transition]
    ) -> None: ...


def _md_windows_by_name(plat: Platform) -> dict[str, object]:
    """One snapshot pass -> {parsed name: handle} for multideck-owned windows."""
    out: dict[str, object] = {}
    for title, handle in plat.snapshot_windows().items():
        parsed = parse_title(title)
        if parsed is not None:
            out[parsed[0]] = handle
    return out


class BadgeRenderer:
    """Keeps every md: window's title badge in sync with its session state.

    Only rewrites when the desired title differs, so a quiet tick makes zero
    Win32 calls. Windows whose parsed name matches no session (e.g. "proj-2"
    secondary windows) are left alone. Known limitation (DESIGN.md): shells
    that rewrite their own titles may overwrite the badge — flash is the
    primary signal, the badge is ambient state."""

    def __init__(self, plat: Platform) -> None:
        self._plat = plat

    def render(self, views: list[SessionView], transitions: list[Transition]) -> None:
        desired = {v.name: v.state for v in views}
        # Materialize first: the ABC doesn't promise a fresh dict, and
        # retitling mid-iteration would mutate a live snapshot under us.
        for title, handle in list(self._plat.snapshot_windows().items()):
            parsed = parse_title(title)
            if parsed is None:
                continue
            name = parsed[0]
            if name not in desired:
                continue
            want = make_title(name, desired[name])
            if want != title:
                self._plat.set_window_title(handle, want)


class FlashRenderer:
    """Flashes the taskbar button when a session ENTERS needs-input/error."""

    def __init__(self, plat: Platform) -> None:
        self._plat = plat

    def render(self, views: list[SessionView], transitions: list[Transition]) -> None:
        names = [t.view.name for t in transitions if t.view.state in PUSH_STATES]
        if not names:
            return
        by_name = _md_windows_by_name(self._plat)
        for name in names:
            handle = by_name.get(name)
            if handle is not None:
                self._plat.flash_window(handle)


class ToastRenderer:
    """Windows toast on needs-input/error transitions. winotify is the
    optional [toast] extra — enabled-but-missing logs one install tip and
    stays quiet after (same optional-dep doctrine as qrcode/sentry-sdk)."""

    def __init__(self, engine: AttentionEngine) -> None:
        self._engine = engine
        self._tip_logged = False

    def render(self, views: list[SessionView], transitions: list[Transition]) -> None:
        for t in transitions:
            v = t.view
            if v.state not in PUSH_STATES:
                continue
            if not self._engine.should_fire(v.cwd, f"toast:{v.state}"):
                continue
            try:
                from winotify import (  # ty: ignore[unresolved-import]  # reason: optional dep, guarded by try/except (the [toast] extra)
                    Notification,
                )
            except ImportError:
                if not self._tip_logged:
                    get_logger("attention").warning(
                        "attention.toast is on but winotify is not installed; "
                        'pip install "multideck[toast]"'
                    )
                    self._tip_logged = True
                return
            Notification(
                app_id="multideck",
                title=f"multideck: {v.name}",
                msg=f"{v.state} — waiting on you",
            ).show()


class NtfyRenderer:
    """POSTs needs-input/error transitions to an ntfy topic URL (from
    MULTIDECK_NTFY_TOPIC). Failures are logged WARNINGs — an unreachable
    notification host must not take the attention loop down."""

    def __init__(self, engine: AttentionEngine, topic_url: str) -> None:
        self._engine = engine
        self._topic = topic_url

    def render(self, views: list[SessionView], transitions: list[Transition]) -> None:
        for t in transitions:
            v = t.view
            if v.state not in PUSH_STATES:
                continue
            if not self._engine.should_fire(v.cwd, f"ntfy:{v.state}"):
                continue
            req = urllib.request.Request(
                self._topic,
                data=f"{v.name}: {v.state}".encode(),
                headers={"Title": f"multideck: {v.name}"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=3):
                    pass
            except (urllib.error.URLError, OSError) as exc:
                get_logger("attention").warning(
                    "ntfy push failed for %s: %s", v.name, exc
                )


# --- Loop --------------------------------------------------------------------


def run_attention_loop(
    engine: AttentionEngine,
    renderers: list[Renderer],
    *,
    poll_interval: float = 2.0,
    max_ticks: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_tick: Callable[[list[SessionView]], None] | None = None,
) -> None:
    """Poll -> diff -> render, forever (or ``max_ticks`` times — test seam /
    one-shot). ``on_tick`` is the daemon's heartbeat hook. Renderer errors
    beyond each renderer's own handled set propagate on purpose."""
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        views = engine.poll()
        transitions = engine.transitions(views)
        for r in renderers:
            r.render(views, transitions)
        if on_tick is not None:
            on_tick(views)
        ticks += 1
        if max_ticks is None or ticks < max_ticks:
            sleep(poll_interval)
