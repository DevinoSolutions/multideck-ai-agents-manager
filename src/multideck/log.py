"""Shared observability: rotating file logging + cross-platform liveness heartbeats.

Every consumer gets its own log file, named by concern, under
``~/.multideck/logs/`` -- runtime state, not config (see cli.py's
_config_dir for the config/*.json home). Logging is best-effort: setup
failures fall back to a NullHandler rather than raising, since the daemons
that call get_logger() run detached with no console to report a crash to.

Heartbeats live here (not in hotkey.py) so cross-platform callers -- `status`,
Linux CI -- can check liveness without importing the Windows-only hotkey
module.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading

LOG_DIR = Path.home() / ".multideck" / "logs"
HEARTBEAT_DIR = Path.home() / ".multideck"

HEARTBEAT_INTERVAL = 10  # seconds between heartbeat writes
HEARTBEAT_MAX_AGE = 30  # 3x the interval, tolerant of scheduler jitter

_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s %(process)d %(name)s %(message)s"

_CONFIGURED_ATTR = "_multideck_log_configured"


def get_logger(name: str) -> logging.Logger:
    """Return the ``multideck.<name>`` logger, attaching a rotating file
    handler under LOG_DIR on first use. Idempotent -- repeat calls return the
    same logger without stacking handlers. Never raises: if LOG_DIR can't be
    created (read-only home, permissions), the logger falls back to a
    NullHandler and stays otherwise usable.
    """
    logger = logging.getLogger(f"multideck.{name}")
    if getattr(logger, _CONFIGURED_ATTR, False):
        return logger

    handler: logging.Handler
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_DIR / f"{name}.log",
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            delay=True,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FORMAT))
    except OSError:
        handler = logging.NullHandler()

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    setattr(logger, _CONFIGURED_ATTR, True)
    return logger


def reset_logging() -> None:
    """Test seam: strip handlers + the configured-sentinel from every
    ``multideck.*`` logger so the next get_logger() call re-attaches under
    whatever LOG_DIR is current (tests monkeypatch it to a tmp_path)."""
    manager = logging.Logger.manager
    for logger_name, logger in list(manager.loggerDict.items()):
        if logger_name != "multideck" and not logger_name.startswith("multideck."):
            continue
        if isinstance(logger, logging.PlaceHolder):
            continue
        for h in list(logger.handlers):
            logger.removeHandler(h)
            h.close()
        if hasattr(logger, _CONFIGURED_ATTR):
            delattr(logger, _CONFIGURED_ATTR)


# --- Liveness heartbeats -----------------------------------------------------
# A daemon (currently: the hotkey listener) touches its heartbeat file on an
# interval; status reads its mtime to tell "running" from "wedged". Freshness
# is judged by mtime, not file contents, so a torn write can't corrupt the
# check.


def _heartbeat_path(name: str) -> Path:
    return HEARTBEAT_DIR / f"{name}.heartbeat"


def write_heartbeat(name: str) -> None:
    """Best-effort liveness pulse. Never raises."""
    try:
        HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
        _heartbeat_path(name).write_text(str(time.time()))
    except OSError:
        pass


def heartbeat_age(name: str) -> float | None:
    """Seconds since the last heartbeat, or None if it was never written."""
    try:
        mtime = _heartbeat_path(name).stat().st_mtime
    except OSError:
        return None
    return time.time() - mtime


def heartbeat_fresh(name: str, max_age: float = HEARTBEAT_MAX_AGE) -> bool:
    age = heartbeat_age(name)
    return age is not None and age <= max_age


def clear_heartbeat(name: str) -> None:
    """Remove a heartbeat file -- the mark of a *clean* daemon shutdown, so
    `status` reads 'off' (never-started) rather than 'crashed' (a heartbeat
    left behind by a process that died without cleaning up). Best-effort:
    never raises."""
    with contextlib.suppress(OSError):
        _heartbeat_path(name).unlink()


def run_heartbeat(name: str, stop_event: threading.Event) -> None:
    """Pulse ``name``'s heartbeat every HEARTBEAT_INTERVAL until ``stop_event``
    is set. Meant to run on a dedicated daemon thread so the liveness signal is
    decoupled from the caller's work cadence: a slow poll loop -- or a user who
    widens that loop's interval past HEARTBEAT_MAX_AGE -- can't make `status`
    read a false 'stale'. Mirrors hotkey.py's heartbeat thread."""
    while not stop_event.is_set():
        write_heartbeat(name)
        stop_event.wait(HEARTBEAT_INTERVAL)
