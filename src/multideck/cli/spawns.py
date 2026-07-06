"""Runtime-probe / daemon-bootstrap leaf: port/pid liveness checks and the
detached-process launchers for the upload server and Alt+V listener. Heavy
subsystems (launch, platform, upload_server) and the platform-guarded hotkey
import stay in-body -- hoisting them would make every command module pay to
import launch/platform at `multideck --help` time (cli/__init__ imports every
command module eagerly to register it).
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path


def _maybe_start_upload_server(port: int, config_path: str | None) -> None:
    """Start the upload server detached, unless something is already on the port."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        probe.connect(("127.0.0.1", port))
    except OSError:
        pass
    else:
        return  # already listening
    finally:
        probe.close()

    args = [sys.executable, "-m", "multideck"]
    if config_path:
        args += ["--config", config_path]
    args += ["serve", "-p", str(port)]
    # heavy subsystem: in-body per policy. Must outlive the SSH bring-up
    # command that spawns it -- see spawn_detached.
    from multideck.launch import spawn_detached

    spawn_detached(args)


def _maybe_start_hotkey(server_url: str) -> int | None:
    """Start the Alt+V listener hidden in the background, unless one is running.

    The listener's progress now shows in the md: windows, so it needs no terminal
    of its own -- attach launches it detached and returns, instead of blocking a
    terminal on a message loop. Returns the listener pid (existing or freshly
    started), or None if it couldn't be confirmed.
    """
    from multideck.platform import get_platform  # heavy subsystem: in-body per policy

    if not get_platform().supports_hotkey():
        return None

    from multideck.hotkey import (
        listener_pid,  # ImportError off-Windows (hotkey.py guards); must stay lazy
    )

    existing = listener_pid()
    if existing:
        return existing

    args = [sys.executable, "-m", "multideck", "hotkey", "-s", server_url]
    from multideck.launch import spawn_detached  # heavy subsystem: in-body per policy

    spawn_detached(args)
    # The child writes its pid only after the keyboard hook installs; give it a
    # short window to come up so we can report (and so a hook failure surfaces).
    for _ in range(20):
        time.sleep(0.1)
        pid = listener_pid()
        if pid:
            return pid
    return None


def _probe_port(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
    except OSError:
        return False
    else:
        return True
    finally:
        s.close()


def _pid_alive(pid: int | None) -> bool:
    """Portable best-effort liveness check for a pid."""
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes  # win-only: ctypes.windll doesn't exist off Windows

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def _running_upload_port() -> int | None:
    """Port of a *live* locally-running upload server, from its pid file. Skips
    stale pid files (a port whose recorded process is gone)."""
    from multideck.upload_server import (
        server_pid,  # heavy subsystem: in-body per policy
    )

    d = Path.home() / ".multideck"
    if not d.exists():
        return None
    ports = []
    for f in d.glob("upload_server-*.pid"):
        m = re.match(r"upload_server-(\d+)\.pid", f.name)
        if m:
            ports.append(int(m.group(1)))
    alive = [p for p in ports if _pid_alive(server_pid(p))]
    return min(alive) if alive else None


def _tailnet_host() -> str:
    """Best host for the phone URL: Tailscale MagicDNS name, then its IP, then
    the LAN IP. MagicDNS gives the prettiest, most stable URL."""

    try:
        r = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            dns = (json.loads(r.stdout).get("Self") or {}).get("DNSName", "")
            if isinstance(dns, str) and dns:
                return dns.rstrip(".")
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    try:
        r = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "localhost"
