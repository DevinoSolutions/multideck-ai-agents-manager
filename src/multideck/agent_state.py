"""Agent-neutral session-state store.

A small file-per-session record of what an agent is doing -- ``working``,
``done`` (your turn), ``needs-input`` (blocked on you), ``error``, ``idle`` --
keyed by the session's working directory. Any agent that can emit lifecycle
events (Claude Code via hooks, Codex via its ``notify`` program, ...) writes
here; the session picker reads here. That keeps status detection out of the
terminal (no scraping) and uniform across agent types.

Deliberately dependency-light (stdlib only) so the hook handler that imports it
adds negligible latency to every turn.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".multideck" / "state"

# Canonical state values.
WORKING = "working"        # a turn is in flight
DONE = "done"              # finished -- waiting on the user
NEEDS_INPUT = "needs-input"  # blocked on the user (permission prompt)
ERROR = "error"            # turn ended on an error
IDLE = "idle"              # session open, nothing pending

_VALID = {WORKING, DONE, NEEDS_INPUT, ERROR, IDLE}


def _norm(path: str) -> str:
    """Canonicalize a path so the writer's cwd and the picker's pane_current_path
    map to the same key. MUST match the notifier's state-sink.mjs ``normCwd``
    (which writes these files for every agent): slashes -> '/', drop trailing
    '/', lowercase on Windows. Deliberately string-only -- no realpath -- so the
    JS and Python sides produce byte-identical keys."""
    s = (path or "").replace("\\", "/").rstrip("/")
    if sys.platform == "win32":
        s = s.lower()
    return s


def _key(path: str) -> str:
    return hashlib.sha1(_norm(path).encode("utf-8")).hexdigest()[:16]


def _path_for(cwd: str) -> Path:
    return STATE_DIR / f"{_key(cwd)}.json"


def write_state(cwd: str, state: str, session_id: str | None = None) -> None:
    if state not in _VALID or not cwd:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path_for(cwd).with_suffix(".tmp")
    payload = json.dumps({
        "state": state,
        "ts": time.time(),
        "cwd": _norm(cwd),
        "session_id": session_id,
    })
    # Write-then-rename so a concurrent reader never sees a half-written file.
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, _path_for(cwd))


def clear_state(cwd: str) -> None:
    if not cwd:
        return
    try:
        _path_for(cwd).unlink()
    except OSError:
        pass


def state_for(cwd: str, max_age: float | None = None) -> dict | None:
    """Return the state record for a cwd, or None if absent/expired."""
    p = _path_for(cwd)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if max_age is not None and (time.time() - d.get("ts", 0)) > max_age:
        return None
    return d
