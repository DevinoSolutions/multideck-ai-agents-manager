"""The psmux session picker: live-session listing (`sessions_cmd`) and the
looping attach-and-return picker (`_run_sessions_picker`). Named
session_picker (not "sessions") to avoid confusion with multideck.sessions.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click

from multideck.cli.app import main
from multideck.cli.config_io import _load_raw_config
from multideck.cli.spawns import _running_upload_port, _tailnet_host
from multideck.cli.ui import _banner, _divider, _menu_item
from multideck.paths import find_config
from multideck.style import style


def _session_cwds(psmux: str, names: list[str]) -> dict[str, str]:
    """Each live session's working directory (psmux ``pane_current_path``) -- the
    key we match against the agent-state store. Fetched concurrently."""

    def cwd(name: str) -> str:
        try:
            r = subprocess.run(
                [psmux, "-L", name, "display-message", "-p", "#{pane_current_path}"],
                capture_output=True,
                text=True,
                timeout=3,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (r.stdout or "").strip()

    with ThreadPoolExecutor(max_workers=16) as pool:
        return dict(zip(names, pool.map(cwd, names), strict=True))


def _status_label(state: str | None) -> str:
    from multideck import agent_state  # heavy subsystem: in-body per policy

    return {
        agent_state.WORKING: style("working...", fg="yellow", bold=True),
        agent_state.DONE: style("done", fg="green", bold=True),
        agent_state.NEEDS_INPUT: style("needs input", fg="red", bold=True),
        agent_state.ERROR: style("error", fg="red", bold=True),
    }.get(state, "")  # type: ignore[arg-type]  # F-D1-005: state is None-safe (.get returns default)


def _session_statuses(cwds: dict[str, str]) -> dict[str, str]:
    """Map each session to a status label read from the agent-state store, which
    agents populate via their own lifecycle events (Claude Code hooks, Codex
    notify, ...) -- ground truth, not terminal scraping. A staleness guard keeps
    a session killed mid-turn from showing 'working...' forever."""
    from multideck import agent_state  # heavy subsystem: in-body per policy

    stale = {agent_state.WORKING: 1800, agent_state.NEEDS_INPUT: 3600}
    out: dict[str, str] = {}
    for sock, cwd in cwds.items():
        rec = agent_state.state_for(cwd) if cwd else None
        state = rec.get("state") if rec else None
        if rec and state in stale and (time.time() - rec.get("ts", 0)) > stale[state]:
            state = None
        out[sock] = _status_label(state)
    return out


_FOCUS_TARGET_FILE = Path.home() / ".multideck" / "focus-target"


_PICKER_ATTACHED_FILE = Path.home() / ".multideck" / "picker-attached"


def _consume_focus_target() -> str | None:
    """Read and clear the session a notification/web tap asked us to jump to."""
    try:
        t = _FOCUS_TARGET_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    with contextlib.suppress(OSError):
        _FOCUS_TARGET_FILE.unlink()
    return t or None


def _set_picker_attached(name: str | None) -> None:
    """Record which session this picker is attached to, so the /focus endpoint
    knows whose client to detach to trigger a switch (None = at the menu)."""
    try:
        if name:
            _PICKER_ATTACHED_FILE.parent.mkdir(parents=True, exist_ok=True)
            _PICKER_ATTACHED_FILE.write_text(name, encoding="utf-8")
        else:
            _PICKER_ATTACHED_FILE.unlink()
    except OSError:
        pass


def _run_sessions_picker(config_file: Path, name: str | None = None) -> None:
    """Looping psmux session picker: list live sessions, attach to a choice, repeat.

    A focus-target file (set by the upload server's /focus endpoint, e.g. from a
    notification tap) lets the currently-attached session be switched remotely:
    /focus detaches this picker's client, the attach returns, and the loop jumps
    straight to the requested project."""

    from multideck.launch import (
        _psmux_session_name,  # heavy subsystem: in-body per policy
    )
    from multideck.platform import find_psmux  # heavy subsystem: in-body per policy

    psmux = find_psmux()
    if not psmux:
        click.echo(
            f"  {style('x', fg='red')} psmux not found on PATH. Install: choco install psmux"
        )
        return

    data = _load_raw_config(config_file)
    sessions: list[str] = []
    for p in data.get("projects", []):
        if not p.get("enabled", True):
            continue
        tool = p.get("tool", data.get("settings", {}).get("defaultTool", "claude"))
        if tool in ("code", "vscode", "cursor"):
            continue
        proj_name = p.get("title") or Path(p["path"]).name
        sock = _psmux_session_name(proj_name)
        if (
            subprocess.run(
                [psmux, "-L", sock, "has-session"], capture_output=True, check=False
            ).returncode
            == 0
        ):
            sessions.append(sock)

    if not sessions:
        click.echo(f"  {style('x', fg='red')} No active psmux sessions.")
        click.echo(
            f"  {style('Run', dim=True)} {style('multideck up', bold=True)} {style('or', dim=True)} "
            f"{style('multideck --go', bold=True)} {style('first.', dim=True)}"
        )
        return

    def _reset_terminal():
        if sys.platform == "win32":
            subprocess.run(["cmd", "/c", "cls"], shell=False, check=False)
        else:
            subprocess.run(["stty", "sane"], capture_output=True, check=False)
            subprocess.run(["tput", "reset"], capture_output=True, check=False)

    def _attach(target):
        # Record the attachment so /focus can detach us to trigger a switch.
        _set_picker_attached(target)
        try:
            subprocess.call([psmux, "-L", target, "attach"])
        finally:
            _set_picker_attached(None)
            _reset_terminal()

    if name:
        matches = [s for s in sessions if name.lower() in s.lower()]
        if matches:
            _attach(matches[0])

    # Tappable from a phone SSH client: one tap opens the uploader, then Add to
    # Home Screen (iOS: tap to install the Web Clip profile). Shown only when a
    # live upload server is detected, so the link always works.
    port = _running_upload_port()
    upload_url = f"http://{_tailnet_host()}:{port}/" if port else None

    while True:
        # Remote switch: a notification/web tap dropped a target here -> jump to it.
        focus = _consume_focus_target()
        if focus and focus in sessions:
            _attach(focus)
            continue

        click.clear()
        _banner()
        click.echo(
            f"  {style('psmux sessions', bold=True)}  {style('(synced with desktop)', dim=True)}"
        )
        _divider()
        click.echo()
        if upload_url:
            click.echo(
                f"  {style('WebApp To Upload Images', bold=True)}  {style(upload_url, fg='cyan', bold=True)}"
            )
            click.echo()
        statuses = _session_statuses(_session_cwds(psmux, sessions))
        for i, sess in enumerate(sessions, 1):
            status = statuses.get(sess, "")
            extra = (" " * max(2, 26 - len(sess)) + status) if status else ""
            _menu_item(str(i), sess, extra=extra)
        click.echo()
        _menu_item("q", "Back", key_fg="yellow")
        click.echo()

        choice = (
            click.prompt(
                f"  {style('attach to', fg='cyan')}",
                default="1",
                show_default=False,
                prompt_suffix=" ",
            )
            .strip()
            .lower()
        )

        if choice == "q":
            return

        target = None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                target = sessions[idx]
        except ValueError:
            matches = [s for s in sessions if choice in s.lower()]
            if matches:
                target = matches[0]

        if target:
            _attach(target)
        else:
            click.echo(f"  {style('x', fg='red')} Invalid choice.")


@main.command("sessions")
@click.argument("name", required=False)
@click.pass_context
def sessions_cmd(ctx: click.Context, name: str | None) -> None:
    """List psmux sessions or attach to one. Usage: multideck sessions [name]"""
    config_file = find_config(ctx.obj.get("config_path"))
    _run_sessions_picker(config_file, name)
