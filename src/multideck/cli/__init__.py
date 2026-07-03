from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from multideck.config import MultideckConfig
from multideck.log import heartbeat_fresh
from multideck.paths import find_config
from multideck.style import S
from multideck.cli.ui import (
    _banner,
    _divider,
    _force_utf8_console,
    _grouped,
    _menu_item,
    _print_names,
    _print_qr,
    _print_session_overview,
)
from multideck.cli.config_io import _load_config_or_exit, _load_raw_config
from multideck.cli.spawns import (
    _maybe_start_hotkey,  # noqa: F401 -- re-exported: test_hotkey.py direct access
    _maybe_start_upload_server,
    _pid_alive,
    _probe_port,
    _running_upload_port,
    _tailnet_host,
)
from multideck.cli.app import main
from multideck.cli.docs import docs_cmd  # noqa: F401 -- import-time command registration
from multideck.cli.config_editor import _config_menu  # noqa: F401 -- re-exported: test_cli_structure characterization
from multideck.cli.menu import _run_discovery, _show_menu  # noqa: F401 -- re-exported: app.py in-body dispatch import
from multideck.cli.attach import (  # noqa: F401 -- re-exported: app.py dispatch + test_attach/test_tiling direct access
    _attach_flow,
    _default_attach_host,
    _split_target,
    _ssh_json,
    _tile_titles,
)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# multideck config ...
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# multideck docs
# ---------------------------------------------------------------------------


@main.command("termius")
@click.option("--host", default=None, help="SSH hostname or IP (default: Tailscale IP)")
@click.option("--user", default=None, help="SSH username (default: current user)")
@click.option("--install", is_flag=True, help="Write entry to ~/.ssh/config")
@click.pass_context
def termius_cmd(ctx: click.Context, host: str | None, user: str | None, install: bool) -> None:
    """Generate SSH config for Termius — one host that opens all projects.

    Connects to the 'multideck' psmux session with all project windows inside.
    Switch windows with Ctrl+B then number/name.
    """
    import getpass
    import subprocess

    if not host:
        try:
            result = subprocess.run(["tailscale", "ip", "-4"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                host = result.stdout.strip().splitlines()[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        if not host:
            host = click.prompt(f"  {S('SSH host/IP', fg='cyan')}", default="localhost")

    if not user:
        user = getpass.getuser()

    marker_start = "# --- multideck-start ---"
    marker_end = "# --- multideck-end ---"

    block = f"""{marker_start}
Host multideck
    HostName {host}
    User {user}
    RemoteCommand multideck sessions
    RequestTTY force
{marker_end}"""

    if install:
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(exist_ok=True)
        ssh_config = ssh_dir / "config"

        existing = ssh_config.read_text(encoding="utf-8") if ssh_config.exists() else ""

        if marker_start in existing:
            import re
            pattern = re.escape(marker_start) + r".*?" + re.escape(marker_end)
            updated = re.sub(pattern, block, existing, flags=re.DOTALL)
        else:
            updated = existing.rstrip() + "\n\n" + block + "\n" if existing else block + "\n"

        ssh_config.write_text(updated, encoding="utf-8")
        click.echo(f"  {S('+', fg='green', bold=True)} Wrote {S('multideck', fg='cyan', bold=True)} host to {S(str(ssh_config), dim=True)}")
        click.echo()
        click.echo(f"  {S('SSH in:', bold=True)} {S('ssh multideck', fg='cyan')} {S('— shows session picker.', dim=True)}")
        click.echo(f"  {S('Pick a project, F1 to go back to the list.', dim=True)}")
    else:
        click.echo(block)
        click.echo()
        click.echo(f"  {S('Add --install to write to ~/.ssh/config', dim=True)}")


@main.command("serve")
@click.option("--port", "-p", default=8033, help="Port to listen on")
@click.option("--host", default=None,
              help="Bind a specific address instead of the default "
                   "(loopback + Tailscale IP, never the LAN wildcard). "
                   "Pass 0.0.0.0 to restore an explicit LAN-wide bind.")
@click.option("--ensure", is_flag=True,
              help="Start the server detached if it isn't already running, then exit (used by attach).")
@click.pass_context
def serve_cmd(ctx: click.Context, port: int, host: str | None, ensure: bool) -> None:
    """Start upload server for mobile image transfer.

    Opens a web page on your phone (via Tailscale) where you pick a project,
    upload an image, and the file path is auto-pasted into that project's
    Claude session via psmux send-keys.
    """
    from multideck.upload_server import _tailscale_ip, run_server

    config_path = ctx.obj.get("config_path")
    if ensure:
        # Non-blocking: ensure a survivor server exists on this port, then return.
        # attach calls this over SSH so the host always has a server for Alt+V,
        # regardless of the uploadServer config flag or whether anything was
        # just brought up.
        _maybe_start_upload_server(port, config_path)
        click.echo(f"upload server ensured on port {port}")
        return

    ip = _tailscale_ip()

    _banner()
    click.echo(f"  {S('Upload server', bold=True)}  {S('for mobile image transfer', dim=True)}")
    _divider()
    click.echo()
    if ip:
        click.echo(f"  {S('Open on phone:', bold=True)}  {S(f'http://{ip}:{port}', fg='cyan', bold=True)}")
    click.echo(f"  {S('Local:', dim=True)}         {S(f'http://localhost:{port}', fg='cyan')}")
    click.echo()
    click.echo(f"  {S('Pick a project, upload a file, path gets pasted into Claude.', dim=True)}")
    click.echo(f"  {S('Ctrl+C to stop.', dim=True)}")
    click.echo()

    try:
        run_server(port=port, config_path=config_path, host=host)
    except KeyboardInterrupt:
        click.echo(f"\n  {S('Server stopped.', dim=True)}")


@main.command("mobile")
@click.option("--port", "-p", default=None, type=int,
              help="Upload server port (default: running server, else 8033).")
@click.option("--host", default=None,
              help="Host/IP for the phone URL (default: Tailscale name or IP).")
@click.pass_context
def mobile_cmd(ctx: click.Context, port: int | None, host: str | None) -> None:
    """Show the phone URL + QR for the image-upload app.

    Scan it once on your phone, then 'Add to Home Screen' to install the
    uploader as a standalone app -- after that it's one tap to send an image
    into any md: session. Run this on the host that serves the uploader.
    """
    _force_utf8_console()
    if port is None:
        port = _running_upload_port() or 8033
    if not host:
        host = _tailnet_host()
    url = f"http://{host}:{port}/"

    _banner()
    click.echo(f"  {S('Mobile uploader', bold=True)}  {S('- install as a home-screen app', dim=True)}")
    _divider()
    click.echo()
    click.echo(f"  {S('Open on phone:', bold=True)}  {S(url, fg='cyan', bold=True)}")
    click.echo()
    _print_qr(url)
    click.echo()
    click.echo(f"  {S('Install:', bold=True)}  {S('iOS', fg='cyan')} Share {S('>', dim=True)} Add to Home Screen"
               f"     {S('Android', fg='cyan')} menu {S('>', dim=True)} Add to Home screen")
    click.echo(f"  {S('Then it opens straight to the uploader - pick a project, send an image.', dim=True)}")
    click.echo()


def _session_cwds(psmux: str, names: list[str]) -> dict[str, str]:
    """Each live session's working directory (psmux ``pane_current_path``) -- the
    key we match against the agent-state store. Fetched concurrently."""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    def cwd(name: str) -> str:
        try:
            r = subprocess.run(
                [psmux, "-L", name, "display-message", "-p", "#{pane_current_path}"],
                capture_output=True, text=True, timeout=3,
                encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return ""
        return (r.stdout or "").strip()

    with ThreadPoolExecutor(max_workers=16) as pool:
        return dict(zip(names, pool.map(cwd, names)))


def _status_label(state: str | None) -> str:
    from multideck import agent_state
    return {
        agent_state.WORKING: S("working...", fg="yellow", bold=True),
        agent_state.DONE: S("done", fg="green", bold=True),
        agent_state.NEEDS_INPUT: S("needs input", fg="red", bold=True),
        agent_state.ERROR: S("error", fg="red", bold=True),
    }.get(state, "")  # type: ignore[arg-type]  # F-D1-005: state is None-safe (.get returns default)


def _session_statuses(cwds: dict[str, str]) -> dict[str, str]:
    """Map each session to a status label read from the agent-state store, which
    agents populate via their own lifecycle events (Claude Code hooks, Codex
    notify, ...) -- ground truth, not terminal scraping. A staleness guard keeps
    a session killed mid-turn from showing 'working...' forever."""
    import time
    from multideck import agent_state
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
    try:
        _FOCUS_TARGET_FILE.unlink()
    except OSError:
        pass
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
    import subprocess

    from multideck.launch import _psmux_session_name
    from multideck.platform import find_psmux

    psmux = find_psmux()
    if not psmux:
        click.echo(f"  {S('x', fg='red')} psmux not found on PATH. Install: choco install psmux")
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
        if subprocess.run([psmux, "-L", sock, "has-session"], capture_output=True).returncode == 0:
            sessions.append(sock)

    if not sessions:
        click.echo(f"  {S('x', fg='red')} No active psmux sessions.")
        click.echo(f"  {S('Run', dim=True)} {S('multideck up', bold=True)} {S('or', dim=True)} "
                   f"{S('multideck --go', bold=True)} {S('first.', dim=True)}")
        return

    def _reset_terminal():
        if sys.platform == "win32":
            subprocess.run(["cmd", "/c", "cls"], shell=False)
        else:
            subprocess.run(["stty", "sane"], capture_output=True)
            subprocess.run(["tput", "reset"], capture_output=True)

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
        click.echo(f"  {S('psmux sessions', bold=True)}  {S('(synced with desktop)', dim=True)}")
        _divider()
        click.echo()
        if upload_url:
            click.echo(f"  {S('WebApp To Upload Images', bold=True)}  {S(upload_url, fg='cyan', bold=True)}")
            click.echo()
        statuses = _session_statuses(_session_cwds(psmux, sessions))
        for i, sess in enumerate(sessions, 1):
            status = statuses.get(sess, "")
            extra = (" " * max(2, 26 - len(sess)) + status) if status else ""
            _menu_item(str(i), sess, extra=extra)
        click.echo()
        _menu_item("q", "Back", key_fg="yellow")
        click.echo()

        choice = click.prompt(
            f"  {S('attach to', fg='cyan')}",
            default="1", show_default=False, prompt_suffix=" ",
        ).strip().lower()

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
            click.echo(f"  {S('x', fg='red')} Invalid choice.")


@main.command("sessions")
@click.argument("name", required=False)
@click.pass_context
def sessions_cmd(ctx: click.Context, name: str | None) -> None:
    """List psmux sessions or attach to one. Usage: multideck sessions [name]"""
    config_file = find_config(ctx.obj.get("config_path"))
    _run_sessions_picker(config_file, name)


# ---------------------------------------------------------------------------
# multideck status / down  (inspect and shut down running sessions/services)
# ---------------------------------------------------------------------------


def _health_check(port: int) -> bool:
    """HTTP GET /health -- proves the upload server is actually SERVING, not
    just that something is bound to the port or that a pid is alive."""
    from urllib.error import URLError
    from urllib.request import urlopen

    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
            data = json.loads(resp.read())
            return bool(data.get("ok"))
    except (URLError, OSError, json.JSONDecodeError):
        return False


def _upload_state(port: int) -> str:
    """"on" (serving) / "dead" (port open or pid alive but not serving --
    the "reports ON while dead" bug, now surfaced) / "off"."""
    if _health_check(port):
        return "on"
    from multideck.upload_server import server_pid
    if _probe_port(port) or _pid_alive(server_pid(port)):
        return "dead"
    return "off"


def _listener_state() -> str:
    """"on" (heartbeat fresh) / "stale" (pid alive, heartbeat expired) / "off"."""
    from multideck.platform import get_platform
    if not get_platform().supports_hotkey():
        return "off"
    from multideck.hotkey import listener_pid
    pid = listener_pid()
    if not pid:
        return "off"
    return "on" if heartbeat_fresh("hotkey") else "stale"


def _gather_status(cfg: MultideckConfig) -> dict[str, str]:
    return {
        "upload_server": _upload_state(cfg.settings.upload_port),
        "listener": _listener_state(),
    }


def _is_degraded(status: dict[str, str]) -> bool:
    return status["upload_server"] == "dead" or status["listener"] == "stale"


def _render_status(config_file: Path) -> bool:
    """Prints the status report; returns True if any daemon is degraded
    (dead/stale). Never exits -- shared with the menu's _menu_status."""
    from multideck.launch import psmux_status

    cfg = _load_config_or_exit(config_file)
    up, down, _ = psmux_status(cfg)

    _banner()
    click.echo(f"  {S('Status', bold=True)}   "
               f"{S(str(len(up)), fg='green', bold=True)} running  {S('/', dim=True)}  "
               f"{S(str(len(down)), fg='yellow', bold=True)} stopped")
    _divider()
    if up:
        order, buckets = _grouped(up)
        for g in order:
            click.echo(f"  {S(g, fg='green', bold=True)}  {S(f'({len(buckets[g])})', dim=True)}")
            _print_names(buckets[g])
    else:
        click.echo(f"  {S('No sessions running.', dim=True)}  "
                   f"{S('Bring some up from the menu or `multideck up`.', dim=True)}")
    if down:
        preview = ", ".join(d["name"] for d in down[:6]) + ("..." if len(down) > 6 else "")
        click.echo(f"\n  {S(str(len(down)), fg='yellow', bold=True)} not running  {S('(' + preview + ')', dim=True)}")
    _divider()

    status = _gather_status(cfg)
    upload_labels = {
        "on": S(f"ON  port {cfg.settings.upload_port}", fg="green", bold=True),
        "dead": S(f"DEAD  port {cfg.settings.upload_port} (not responding)", fg="red", bold=True),
        "off": S("off", dim=True),
    }
    click.echo(f"  {S('Upload server', bold=True)}   {upload_labels[status['upload_server']]}")

    listener_labels = {
        "on": S("ON", fg="green", bold=True),
        "stale": S("STALE  (heartbeat expired)", fg="red", bold=True),
        "off": S("off  (starts with `multideck attach`)", dim=True),
    }
    click.echo(f"  {S('Alt+V listener', bold=True)}   {listener_labels[status['listener']]}")

    return _is_degraded(status)


@main.command("status")
@click.option("--json", "as_json", is_flag=True, help="Print daemon status as JSON")
@click.pass_context
def status_cmd(ctx: click.Context, as_json: bool) -> None:
    """Show which psmux sessions and services are currently running."""
    config_file = find_config(ctx.obj.get("config_path"))
    if not config_file.exists():
        if as_json:
            click.echo(json.dumps({"error": "No config found."}))
        else:
            click.echo("No config found. Run multideck first.", err=True)
        sys.exit(1)

    if as_json:
        cfg = _load_config_or_exit(config_file)
        status = _gather_status(cfg)
        click.echo(json.dumps(status))
        sys.exit(3 if _is_degraded(status) else 0)

    if _render_status(config_file):
        sys.exit(3)


@main.command("down")
@click.argument("names", nargs=-1)
@click.option("-g", "--group", default=None, help="Only sessions in this group")
@click.option("--all", "do_all", is_flag=True,
              help="Stop every session, the upload server, and the Alt+V listener")
@click.option("--server", "stop_srv", is_flag=True, help="Also stop the upload server")
@click.pass_context
def down_cmd(ctx: click.Context, names: tuple[str, ...], group: str | None,
             do_all: bool, stop_srv: bool) -> None:
    """Shut down running psmux sessions (and optionally the upload server)."""
    config_file = find_config(ctx.obj.get("config_path"))
    cfg = _load_config_or_exit(config_file)

    from multideck.launch import kill_psmux, psmux_status

    up, _, _ = psmux_status(cfg, group=group)
    up_names = [u["name"] for u in up]
    if names:
        wanted = {n.lower() for n in names}
        targets = [n for n in up_names if n.lower() in wanted]
    else:
        targets = up_names

    if targets:
        kill_psmux(targets)
        click.echo(f"  {S('+', fg='green')} Stopped {S(str(len(targets)), fg='green', bold=True)}"
                   f" session(s): {S(', '.join(targets), dim=True)}")
    else:
        click.echo(f"  {S('-', dim=True)} No matching running sessions.")

    if do_all or stop_srv:
        from multideck.upload_server import stop_server
        if stop_server(cfg.settings.upload_port):
            click.echo(f"  {S('+', fg='green')} Stopped upload server on port {cfg.settings.upload_port}.")
        else:
            click.echo(f"  {S('-', dim=True)} Upload server not running, or could not be stopped (see logs).")

    from multideck.platform import get_platform
    if do_all and get_platform().supports_hotkey():
        from multideck.hotkey import stop_listener
        if stop_listener():
            click.echo(f"  {S('+', fg='green')} Stopped the Alt+V listener.")
        else:
            click.echo(f"  {S('-', dim=True)} Alt+V listener was not running.")


def _menu_status(config_file: Path) -> None:
    _render_status(config_file)
    click.echo()
    click.pause(info=f"  {S('press any key to return', dim=True)}")


def _menu_up(config_file: Path) -> None:
    from multideck.launch import bring_up_psmux, psmux_status

    cfg = _load_config_or_exit(config_file)
    up, down, projects = psmux_status(cfg)
    _banner()
    click.echo(f"  {S('Bring up sessions in background', bold=True)}  {S('(no windows)', dim=True)}")
    _divider()
    if not projects:
        click.echo(f"  {S('!', fg='yellow')} No psmux-eligible projects in config.")
    elif not down:
        click.echo(f"  {S('+', fg='green')} All {len(up)} session(s) already running.")
    else:
        dn_order, dn_buckets = _grouped(down)
        pickable = _print_session_overview("this machine", up, down)
        opts = [f"{S('a', fg='cyan', bold=True)}=all {len(down)}"]
        if pickable:
            opts.append(f"{S('1-' + str(len(pickable)), fg='cyan', bold=True)}=one group")
        opts.append(f"{S('n', fg='cyan', bold=True)}=cancel")
        click.echo(f"  {S('Bring up', bold=True)}   " + "   ".join(opts))
        choice = click.prompt(f"  {S('>', fg='cyan', bold=True)}", default="a",
                              show_default=False, prompt_suffix=" ").strip().lower()
        if choice in ("n", "no", "cancel", "q"):
            return
        if choice in ("a", "all", "y", ""):
            only = [d["name"] for d in down]
        elif choice.isdigit() and 1 <= int(choice) <= len(pickable):
            only = dn_buckets[pickable[int(choice) - 1]]
        else:
            sel = next((g for g in pickable if g.lower() == choice), None)
            if not sel:
                click.echo(f"  {S('?', fg='yellow')} cancelled.")
                return
            only = dn_buckets[sel]
        created = bring_up_psmux(cfg, only=only)
        click.echo(f"  {S('+', fg='green')} Brought up {S(str(len(created)), fg='green', bold=True)} "
                   f"session(s) headlessly {S('(switch with the session switcher)', dim=True)}.")
        if cfg.settings.upload_server:
            _maybe_start_upload_server(cfg.settings.upload_port, str(config_file))
    click.echo()
    click.pause(info=f"  {S('press any key to return', dim=True)}")


def _menu_down(config_file: Path) -> None:
    from multideck.launch import kill_psmux, psmux_status

    cfg = _load_config_or_exit(config_file)
    up, _, _ = psmux_status(cfg)
    _banner()
    click.echo(f"  {S('Shut down sessions', bold=True)}")
    _divider()
    if not up:
        click.echo(f"  {S('-', dim=True)} Nothing is running.")
    else:
        order, buckets = _grouped(up)
        for g in order:
            click.echo(f"  {S(g, fg='green', bold=True)}  {S(f'({len(buckets[g])})', dim=True)}")
            _print_names(buckets[g])
        pickable = [g for g in order if g != "(no group)"]
        srv_on = _probe_port(cfg.settings.upload_port)
        click.echo()
        opts = [f"{S('a', fg='cyan', bold=True)}=all {len(up)}"]
        if pickable:
            opts.append(f"{S('1-' + str(len(pickable)), fg='cyan', bold=True)}=one group")
        if srv_on:
            opts.append(f"{S('x', fg='cyan', bold=True)}=all + server")
        opts.append(f"{S('n', fg='cyan', bold=True)}=cancel")
        click.echo(f"  {S('Shut down', bold=True)}   " + "   ".join(opts))
        choice = click.prompt(f"  {S('>', fg='cyan', bold=True)}", default="n",
                              show_default=False, prompt_suffix=" ").strip().lower()
        also_server = False
        if choice in ("n", "no", "cancel", "q", ""):
            return
        if choice in ("a", "all", "y"):
            targets = [u["name"] for u in up]
        elif choice == "x":
            targets = [u["name"] for u in up]
            also_server = True
        elif choice.isdigit() and 1 <= int(choice) <= len(pickable):
            targets = buckets[pickable[int(choice) - 1]]
        else:
            sel = next((g for g in pickable if g.lower() == choice), None)
            if not sel:
                click.echo(f"  {S('?', fg='yellow')} cancelled.")
                return
            targets = buckets[sel]
        kill_psmux(targets)
        click.echo(f"  {S('+', fg='green')} Stopped {S(str(len(targets)), fg='green', bold=True)} session(s).")
        if also_server:
            from multideck.upload_server import stop_server
            stop_server(cfg.settings.upload_port)
            click.echo(f"  {S('+', fg='green')} Stopped upload server.")
    click.echo()
    click.pause(info=f"  {S('press any key to return', dim=True)}")
