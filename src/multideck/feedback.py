"""Cross-platform terminal feedback for the Alt+V clipboard-upload hotkey.

Prints a concise, append-only progress log to the listener's own terminal -- one
line when an upload starts and one when it resolves -- so you can see that a
paste was captured and whether it landed, without ever drawing into the focused
session window (which runs a TUI and must not be disturbed).

Each upload gets a small ``#id`` and the project name, so several pastes in
flight at once stay legible and their start / finish lines pair up. No popups, no
sound, no GUI toolkit, no third-party dependency -- just colored stdout,
identical on Windows, macOS, and Linux. Set ``MULTIDECK_NO_FEEDBACK=1`` to
disable.
"""
from __future__ import annotations

import itertools
import os
import sys
import threading
import time

# stage -> (unicode glyph, ANSI color, ASCII fallback glyph)
_STAGES = {
    "start": ("↑", "36", ">"),   # cyan
    "ok":    ("✓", "32", "+"),   # green
    "fail":  ("✗", "31", "x"),   # red
}

_counter = itertools.count(1)
_lock = threading.Lock()
_active: dict[int, tuple[str, float]] = {}


def enabled() -> bool:
    return os.environ.get("MULTIDECK_NO_FEEDBACK", "") in ("", "0", "false", "False")


def init_console() -> None:
    """Best-effort: make this process's console render UTF-8 so the ✓/↑/✗ glyphs
    show correctly regardless of which terminal hosts the listener. Call once at
    listener startup.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Python 3.7+
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass


def begin(project: str):
    """A paste was captured: log a start line and return an id for finish()."""
    if not enabled():
        return None
    uid = next(_counter)
    with _lock:
        _active[uid] = (project, time.monotonic())
    _line("start", uid, project, None)
    return uid


def finish(handle, project: str, ok: bool) -> None:
    """An upload resolved: log a check (ok) or cross (fail) line for its id."""
    if not enabled() or handle is None:
        return
    with _lock:
        info = _active.pop(handle, None)
    elapsed = time.monotonic() - info[1] if info else None
    _line("ok" if ok else "fail", handle, project, elapsed)


def _tail(stage: str, elapsed: float | None) -> str:
    if stage == "start":
        return "uploading..."
    secs = f" ({elapsed:.1f}s)" if elapsed is not None else ""
    return ("sent" if stage == "ok" else "failed") + secs


def _line(stage: str, uid: int, project: str, elapsed: float | None) -> None:
    glyph, color, ascii_glyph = _STAGES[stage]
    body = f"#{uid}  {project}  {_tail(stage, elapsed)}"
    # Serialize writes so concurrent uploads can't interleave a half-line.
    with _lock:
        try:
            print(f"  \033[{color}m{glyph} {body}\033[0m", flush=True)
        except UnicodeEncodeError:
            print(f"  {ascii_glyph} {body}", flush=True)
        except Exception:
            pass
