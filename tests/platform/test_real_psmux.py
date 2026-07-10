"""REAL psmux server lifecycle: a uniquely-named detached session brought up
through the same platform primitive the launch path uses, then interrogated
and torn down through the psmux module's real subprocess primitives.

What this proves (against a live psmux server, zero stubs):

* ``platform.launch_psmux_session`` really creates a detached session
  (``has_session`` true) rooted at the requested cwd;
* ``psmux.pane_cwd`` (the #41 pane_cwd guard's happy path) reports that REAL
  working directory back from the live pane;
* after ``kill_server``, ``pane_cwd`` degrades to ``""`` promptly (well inside
  its 3s subprocess-timeout guard) and ``has_session`` is false -- the exact
  degradation the guard promises callers that fan this across sessions.

Skips cleanly when psmux is not installed or the platform has no psmux
support (macOS/Linux, and CI runners without the binary).
"""

import os
import time
import uuid
from pathlib import Path

import pytest

from multideck import psmux
from multideck.platform import PsmuxWindowOpts, get_platform

pytestmark = [
    pytest.mark.platform,
    pytest.mark.skipif(psmux.find_psmux() is None, reason="psmux not installed"),
    pytest.mark.skipif(
        not get_platform().supports_psmux(),
        reason="platform backend has no psmux session support",
    ),
]


def _wait_until(check, timeout: float, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            return result
        time.sleep(interval)


def _norm_path(p: str) -> str:
    """Tolerant path normalizer for comparing psmux's pane_current_path (which
    may come back cygwin-style, e.g. /c/Users/... or /cygdrive/c/...) against a
    Windows path -- forward slashes, drive letter unified, casefolded."""
    s = p.strip().replace("\\", "/")
    for prefix in ("/cygdrive/", "/"):
        rest = s[len(prefix) :]
        if (
            s.startswith(prefix)
            and len(rest) >= 2
            and rest[1] == "/"
            and rest[0].isalpha()
        ):
            s = f"{rest[0]}:{rest[1:]}"
            break
    return s.rstrip("/").casefold()


def _same_dir(reported: str, expected: Path) -> bool:
    if not reported:
        return False
    try:
        if os.path.exists(reported) and os.path.samefile(reported, expected):
            return True
    except OSError:
        pass
    return _norm_path(reported) == _norm_path(str(expected))


def test_real_session_pane_cwd_and_kill(tmp_path):
    unique = uuid.uuid4().hex[:12]
    name = f"mdrl-psx-{unique}"
    workdir = tmp_path / f"cwd-{unique}"
    workdir.mkdir()

    created = False
    try:
        # Bring the session up the way run_multideck does: through the
        # platform primitive (real `psmux new-session -d -c <cwd>` + send-keys).
        get_platform().launch_psmux_session(
            [
                PsmuxWindowOpts(
                    window_name=name,
                    cwd=str(workdir),
                    command=f"rem mdrl-{unique}",
                )
            ]
        )
        created = True

        assert _wait_until(lambda: psmux.has_session(name), timeout=10), (
            f"psmux session {name!r} never came up"
        )

        reported = _wait_until(lambda: psmux.pane_cwd(name), timeout=15)
        assert _same_dir(reported, workdir), (
            f"pane_cwd reported {reported!r}, expected {workdir}"
        )

        # Kill THIS session's server and watch the primitives degrade honestly.
        assert psmux.kill_server(name), f"kill_server({name!r}) failed"

        assert _wait_until(
            lambda: not psmux.has_session(name) and psmux.pane_cwd(name) == "",
            timeout=3.5,
        ), "session still answering ~3s after kill_server"

        # The pane_cwd timeout guard, for real: a call against the dead server
        # returns "" and does so promptly (bounded by its own 3s guard).
        start = time.monotonic()
        assert psmux.pane_cwd(name) == ""
        assert time.monotonic() - start < 4.0, "pane_cwd exceeded its timeout guard"
    finally:
        if created:
            psmux.kill_server(name)  # idempotent; only ever targets our name

    assert not psmux.has_session(name), f"cleanup left psmux session {name!r} alive"
