from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable

import click

from multideck.config import MultideckConfig, ProjectConfig
from multideck.grid import TileSlot, compute_grid
from multideck.log import get_logger
from multideck.platform import Platform, PsmuxWindowOpts, TerminalLaunchOpts, VSCodeLaunchOpts, get_platform
from multideck.sessions import AGENT_TOOLS, build_resume_command
from multideck.style import S
from multideck.tiling import Placement, place_windows
from multideck.titles import generate_titles, get_leaf_name


def spawn_detached(args: list[str], extra_flags: int = 0) -> "subprocess.Popen":
    """Popen a process that outlives both this process and a launching SSH session.

    On Windows, OpenSSH puts the command's children in a job object marked
    kill-on-close, so when the SSH session ends the children are terminated.
    ``DETACHED_PROCESS`` only detaches the console -- it does not escape the job.
    ``CREATE_BREAKAWAY_FROM_JOB`` does, but CreateProcess fails outright if the
    parent job forbids breakaway, so fall back to a plain detached spawn (the
    normal case when launched from an interactive console, not under a job).
    """
    if sys.platform != "win32":
        return subprocess.Popen(args)
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    base = CREATE_NO_WINDOW | DETACHED_PROCESS | extra_flags
    try:
        return subprocess.Popen(args, creationflags=base | CREATE_BREAKAWAY_FROM_JOB)
    except OSError:
        return subprocess.Popen(args, creationflags=base)


@dataclass
class RunOpts:
    retile_all: bool = False
    dry_run: bool = False
    group: str | None = None
    config_path: str = ""


@dataclass
class _Target:
    name: str
    key: str
    mode: str
    is_new: bool


def _resolve_path(raw: str, base_dir: str | None) -> str | None:
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if os.path.isabs(expanded):
        return expanded if os.path.isdir(expanded) else None
    if base_dir:
        joined = os.path.join(base_dir, expanded)
        return joined if os.path.isdir(joined) else None
    return None


def _get_session_ids(tool: str, project_dir: str, count: int) -> list[str | None]:
    caps = AGENT_TOOLS.get(tool)
    if caps and caps.session_ids:
        return caps.session_ids(project_dir, count)
    return [None] * count


HAPPY_AGENTS = {t for t, c in AGENT_TOOLS.items() if c.happy}   # derived; name kept for tests


def _get_tailscale_ip() -> str | None:
    import subprocess
    try:
        result = subprocess.run(["tailscale", "ip", "-4"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _psmux_session_name(title: str) -> str:
    """Sanitize a window title into a valid psmux/tmux session name."""
    return title.replace(".", "-").replace(":", "-").replace(" ", "-")


def _wrap_happy(tool: str, cmd: str) -> str:
    """Wrap a CLI agent command with Happy for mobile/web access."""
    if tool in HAPPY_AGENTS:
        return f"happy {cmd}"
    return cmd


def run_multideck(config: MultideckConfig, opts: RunOpts) -> int:
    log = get_logger("launch")
    plat = get_platform()

    slots = _prepare_grid(plat, config, opts)
    if slots is None:
        log.error("no monitors detected; aborting")
        click.echo(f"  {S('✗', fg='red')} No monitors detected.", err=True)
        return 2

    projects = _select_projects(config, opts)
    if projects is None:
        return 0

    base_dir = config.base_dir
    if base_dir:
        base_dir = os.path.expandvars(os.path.expanduser(base_dir)).replace("/", os.sep)

    result = _launch_projects(plat, config, opts, projects, base_dir)

    _start_psmux_and_upload(plat, config, opts, result)

    _tile_targets(plat, opts, slots, result.targets)

    return 0


def _prepare_grid(plat: Platform, config: MultideckConfig, opts: RunOpts) -> list[TileSlot] | None:
    """DPI-init, enumerate monitors, compute the tile grid, print the grid/
    dry-run banner. Returns the tile slots, or None when no monitors are
    detected -- the caller owns the no-monitors echo/log/exit code."""
    plat.set_dpi_aware()

    monitors = plat.list_monitors()
    if not monitors:
        return None

    slots = compute_grid(monitors, config.layout.columns, config.layout.rows)

    grid_label = f"{config.layout.columns}x{config.layout.rows}"
    click.echo(
        f"\n  {S('#', fg='cyan')} {S(str(len(monitors)), fg='cyan', bold=True)} screen(s)  "
        f"{S('->', dim=True)}  {S(str(len(slots)), fg='green', bold=True)} tile slots  "
        f"{S(f'({grid_label} per screen)', dim=True)}"
    )
    if opts.dry_run:
        click.echo(f"  {S('! DRY RUN', fg='yellow', bold=True)} {S('-- nothing will be launched or moved.', dim=True)}\n")

    return slots


def _select_projects(config: MultideckConfig, opts: RunOpts) -> list[ProjectConfig] | None:
    """Enabled projects, optionally narrowed to opts.group. Returns None
    (caller exits 0) when a named group matches nothing (after printing the
    same 'No projects in group' message it does today)."""
    projects = [p for p in config.projects if p.enabled]
    if opts.group:
        projects = [p for p in projects if p.group and p.group.lower() == opts.group.lower()]
        if not projects:
            groups = sorted({p.group for p in config.projects if p.group})
            click.echo(f"No projects in group '{opts.group}'. Available: {', '.join(groups)}", err=True)
            return None
        click.echo(f"Group '{opts.group}': {len(projects)} project(s)")
    return projects


@dataclass(frozen=True)
class _LaunchResult:
    """Everything the launch phase produces for the downstream phases."""
    targets: list[_Target]
    psmux_windows: list[PsmuxWindowOpts]
    psmux_colors: dict[str, str | None]


def _launch_projects(plat: Platform, config: MultideckConfig, opts: RunOpts,
                     projects: list[ProjectConfig], base_dir: str | None) -> _LaunchResult:
    """The per-project dispatch loop: launch IDEs/terminals (or collect psmux
    windows), build the tiling target list. Pure w.r.t. tiling -- it never
    moves a window."""
    has_remote = any(p.host for p in projects)
    if has_remote and not shutil.which("ssh"):
        click.echo(S("  ! Remote projects configured but 'ssh' not on PATH.", fg="yellow"))

    targets: list[_Target] = []
    new_count = 0
    tools = config.settings.tools
    use_psmux = config.settings.psmux and plat.supports_psmux()
    psmux_windows: list[PsmuxWindowOpts] = []
    _psmux_colors: dict[str, str | None] = {}

    win_snapshot = plat.snapshot_windows()

    def _is_running(key: str, mode: str) -> bool:
        if mode == "exact":
            return key in win_snapshot
        return any(key.lower() in t.lower() for t in win_snapshot)

    for proj in projects:
        tool = proj.tool or config.settings.default_tool
        is_remote = bool(proj.host)

        if tool in ("code", "vscode", "cursor"):
            new_count += _dispatch_ide_project(
                plat, config, opts, proj, tool, is_remote, base_dir, _is_running, targets,
            )
            continue

        new_count += _dispatch_cli_agent_project(
            plat, config, opts, proj, tool, is_remote, base_dir, tools, use_psmux,
            _is_running, targets, psmux_windows, _psmux_colors,
        )

    return _LaunchResult(targets=targets, psmux_windows=psmux_windows, psmux_colors=_psmux_colors)


def _dispatch_ide_project(plat: Platform, config: MultideckConfig, opts: RunOpts,
                          proj: ProjectConfig, tool: str, is_remote: bool, base_dir: str | None,
                          is_running: Callable[[str, str], bool],
                          targets: list[_Target]) -> int:
    """Launch (or skip, if already running) a code/vscode/cursor project's
    IDE window; append its tiling target to the caller-owned `targets` list.
    Returns the new_count delta (1 if newly launched, 0 if already running)."""
    key = get_leaf_name(proj.remote_path or proj.path) if is_remote else get_leaf_name(proj.path)
    name = proj.title or key
    running = is_running(key, "contains")
    if not running and not opts.dry_run:
        vsc_dir = proj.remote_path or proj.path if is_remote else (_resolve_path(proj.path, base_dir) or proj.path)
        ide_cmd = "cursor" if tool == "cursor" else "code"
        plat.launch_vscode(VSCodeLaunchOpts(
            dir=vsc_dir,
            ssh_host=proj.host if is_remote else None,
            command=ide_cmd,
        ))
        time.sleep(config.settings.launch_delay_ms / 1000)
    new_count_delta = 0 if running else 1
    targets.append(_Target(name=name, key=key, mode="contains", is_new=not running))
    _log_project(name, tool, running, proj.host, happy=False)
    return new_count_delta


def _dispatch_cli_agent_project(plat: Platform, config: MultideckConfig, opts: RunOpts,
                                proj: ProjectConfig, tool: str, is_remote: bool, base_dir: str | None,
                                tools: dict[str, str], use_psmux: bool,
                                is_running: Callable[[str, str], bool],
                                targets: list[_Target],
                                psmux_windows: list[PsmuxWindowOpts],
                                psmux_colors: dict[str, str | None]) -> int:
    """Generate this project's window titles, resolve resumable sessions, and
    launch (or collect into the caller-owned `psmux_windows`) each window;
    append its tiling target(s) to the caller-owned `targets` list. Returns
    the new_count delta (windows newly launched or newly collected, summed
    across every window this project owns)."""
    new_count = 0

    windows_cfg = proj.windows
    if is_remote or tool in ("code", "vscode", "cursor"):
        windows_cfg = None
    titles = generate_titles(proj.title, proj.path, windows_cfg)
    window_count = len(titles)

    session_ids: list[str | None] = [None] * window_count
    caps = AGENT_TOOLS.get(tool)
    if window_count > 1 and caps and caps.multi_window and not is_remote:
        resolved_dir = _resolve_path(proj.path, base_dir)
        if resolved_dir:
            session_ids = _get_session_ids(tool, resolved_dir, window_count)

    base_cmd = tools.get(tool)
    if not base_cmd:
        click.echo(f"SKIP: {titles[0]} — unknown tool '{tool}' (add under settings.tools)")
        return new_count

    use_happy = proj.happy if proj.happy is not None else config.settings.happy

    for i, win_title in enumerate(titles):
        if window_count > 1 and session_ids[i] is not None:
            cmd = build_resume_command(tool, base_cmd, session_ids[i])
        elif window_count > 1:
            cmd = build_resume_command(tool, base_cmd, None)
        else:
            cmd = base_cmd

        if use_happy:
            cmd = _wrap_happy(tool, cmd)

        proj_psmux = use_psmux and not is_remote
        if proj_psmux and not opts.dry_run:
            resolved_dir = _resolve_path(proj.path, base_dir)
            if resolved_dir:
                wname = _psmux_session_name(win_title)
                psmux_windows.append(PsmuxWindowOpts(
                    window_name=wname,
                    cwd=resolved_dir,
                    command=cmd,
                ))
                psmux_colors[wname] = proj.color
        running = is_running(win_title, "exact")
        if not running and not opts.dry_run and not proj_psmux:
            if is_remote:
                resolved_dir = proj.remote_path or proj.path
                plat.launch_terminal(TerminalLaunchOpts(
                    title=win_title,
                    cwd=os.getcwd(),
                    command=cmd,
                    color=proj.color,
                    ssh_host=proj.host,
                    ssh_remote_dir=resolved_dir,
                    ssh_shell=config.settings.ssh.shell,
                ))
            else:
                resolved_dir = _resolve_path(proj.path, base_dir)
                if not resolved_dir:
                    click.echo(f"SKIP: {proj.path} not found")
                    continue
                plat.launch_terminal(TerminalLaunchOpts(
                    title=win_title,
                    cwd=resolved_dir,
                    command=cmd,
                    color=proj.color,
                ))
            if not proj_psmux:
                time.sleep(config.settings.launch_delay_ms / 1000)
        if not running:
            new_count += 1
        targets.append(_Target(name=win_title, key=win_title, mode="exact", is_new=not running))
        _log_project(win_title, tool, running, proj.host, happy=use_happy, psmux=proj_psmux)

    return new_count


def _start_psmux_and_upload(plat: Platform, config: MultideckConfig, opts: RunOpts,
                            result: _LaunchResult) -> None:
    """Create + attach the collected psmux sessions and, when configured,
    spawn the upload server. No-op when result.psmux_windows is empty or dry_run."""
    psmux_windows = result.psmux_windows
    psmux_colors = result.psmux_colors
    if psmux_windows and not opts.dry_run:
        plat.launch_psmux_session(psmux_windows)
        for pw in psmux_windows:
            plat.attach_psmux(pw.window_name, pw.window_name,
                              psmux_colors.get(pw.window_name))
        click.echo(f"\n  {S('#', fg='yellow')} psmux: {S(str(len(psmux_windows)), fg='yellow', bold=True)} sessions"
                    f" {S('(synced with mobile)', dim=True)}")
        click.echo(f"  {S('From SSH:', dim=True)} {S('psmux -L <name> attach', fg='cyan')}"
                    f" {S('or', dim=True)} {S('multideck sessions', fg='cyan')}")

        if config.settings.upload_server:
            port = config.settings.upload_port
            python = sys.executable
            serve_args = [python, "-m", "multideck"]
            if opts.config_path:
                serve_args.extend(["--config", opts.config_path])
            serve_args.extend(["serve", "-p", str(port)])
            spawn_detached(serve_args)
            ip = _get_tailscale_ip()
            url = f"http://{ip}:{port}" if ip else f"http://localhost:{port}"
            click.echo(f"\n  {S('#', fg='magenta')} upload server: {S(url, fg='cyan', bold=True)}"
                        f" {S('(open on phone)', dim=True)}")


def _tile_targets(plat: Platform, opts: RunOpts, slots: list[TileSlot], targets: list[_Target]) -> None:
    """Place (or, under dry_run, preview) each target into a slot. Delegates
    the resolve-and-move-with-retry logic to multideck.tiling.place_windows
    (R13/E9's shared helper) -- no lookup/retry loop is re-implemented here."""
    to_place = targets if opts.retile_all else [t for t in targets if t.is_new]

    if not to_place:
        click.echo(f"\n  {S('+', fg='green')} All windows already positioned.")
        return

    mode_label = S(" retile all", fg="yellow") if opts.retile_all else (S(" dry run", fg="yellow") if opts.dry_run else "")
    click.echo(f"\n  {S('#', fg='cyan')} Tiling {S(str(len(to_place)), fg='cyan', bold=True)} window(s)...{mode_label}")

    if opts.dry_run:
        for slot_idx, target in enumerate(to_place):
            pos = slots[slot_idx % len(slots)]
            screen_num = pos.monitor_index + 1
            dims = S(f"{pos.w}x{pos.h}", dim=True)
            at = S(f"({pos.x},{pos.y})", dim=True)
            click.echo(f"    {S('>', fg='cyan')} {target.name:<28} {S('->', dim=True)} screen {screen_num}  {dims} {at}")
        click.echo(f"\n  {S('Done!', fg='green', bold=True)}")
        return

    placements = [
        Placement(name=target.name, key=target.key, mode=target.mode, slot=slots[i % len(slots)])
        for i, target in enumerate(to_place)
    ]

    def _placed(p: Placement) -> None:
        click.echo(f"    {S('+', fg='green')} {p.name} {S('->', dim=True)} screen {p.slot.monitor_index + 1}")

    def _missing(p: Placement) -> None:
        click.echo(f"    {S('x', fg='red')} {p.name} {S('not found', dim=True)}")

    place_windows(plat, placements, on_placed=_placed, on_missing=_missing)

    click.echo(f"\n  {S('Done!', fg='green', bold=True)}")


def _log_project(name: str, tool: str, running: bool, host: str | None,
                  happy: bool = False, psmux: bool = False) -> None:
    if running:
        icon = S("*", fg="green")
        label = S("open", dim=True)
    else:
        icon = S("o", fg="cyan")
        label = S("new", fg="cyan")
    loc = S(f" @ {host}", dim=True) if host else ""
    tool_badge = S(f"[{tool}]", dim=True)
    extras = ""
    if happy:
        extras += S(" [happy]", fg="magenta")
    if psmux:
        extras += S(" [psmux]", fg="yellow")
    click.echo(f"  {icon} {name:<30} {label}  {tool_badge}{extras}{loc}")


# ---------------------------------------------------------------------------
# Headless psmux session management -- the host side of `multideck attach`.
# These never open GUI windows, so they work over a plain SSH command.
# ---------------------------------------------------------------------------

def eligible_psmux_projects(config: MultideckConfig, group: str | None = None) -> list[dict]:
    """Projects that map to a persistent psmux session.

    A project is eligible when it is enabled, runs a CLI agent (not an IDE),
    and is local to this machine (no ``host`` -- remote projects are launched
    over SSH directly, not via psmux). When ``group`` is given, only projects
    tagged with that group (case-insensitive) are returned.
    """
    base_dir = config.base_dir
    if base_dir:
        base_dir = os.path.expandvars(os.path.expanduser(base_dir)).replace("/", os.sep)

    out: list[dict] = []
    for proj in config.projects:
        if not proj.enabled:
            continue
        if group and (not proj.group or proj.group.lower() != group.lower()):
            continue
        tool = proj.tool or config.settings.default_tool
        if tool in ("code", "vscode", "cursor"):
            continue
        if proj.host:
            continue
        leaf = proj.title or get_leaf_name(proj.path)
        out.append({
            "name": _psmux_session_name(leaf),
            "path": proj.path,
            "tool": tool,
            "group": proj.group,
            "resolved": _resolve_path(proj.path, base_dir),
            "cmd": config.settings.tools.get(tool, ""),
            "color": proj.color,
        })
    return out


def psmux_status(config: MultideckConfig, group: str | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Return ``(up, down, all_projects)`` for eligible projects.

    ``up``/``down`` are split by whether a live psmux session already exists.
    """
    from multideck.platform import find_psmux

    psmux = find_psmux()
    projects = eligible_psmux_projects(config, group)
    up: list[dict] = []
    down: list[dict] = []

    checkable = []
    for p in projects:
        info = {"name": p["name"], "path": p["path"], "tool": p["tool"], "group": p.get("group")}
        if psmux and p["resolved"] and p["cmd"]:
            proc = subprocess.Popen([psmux, "-L", p["name"], "has-session"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            checkable.append((info, proc))
        else:
            down.append(info)

    for info, proc in checkable:
        (up if proc.wait() == 0 else down).append(info)

    return up, down, projects


def bring_up_psmux(config: MultideckConfig, only: list[str] | None = None,
                   group: str | None = None) -> list[str]:
    """Create detached psmux sessions for eligible projects.

    ``only`` restricts creation to the given session names (pass the ``down``
    set to avoid disturbing sessions that are already running); ``group``
    restricts to a single project group. Returns the names that were
    (re)created.
    """
    from multideck.platform import PsmuxWindowOpts, get_platform

    plat = get_platform()
    windows: list[PsmuxWindowOpts] = []
    for p in eligible_psmux_projects(config, group):
        if only is not None and p["name"] not in only:
            continue
        if not p["resolved"] or not p["cmd"]:
            continue
        windows.append(PsmuxWindowOpts(
            window_name=p["name"], cwd=p["resolved"], command=p["cmd"],
        ))
    if windows:
        plat.launch_psmux_session(windows)
    return [w.window_name for w in windows]


def kill_psmux(names: list[str]) -> list[str]:
    """Kill the psmux server backing each named session. Returns the names tried."""
    from multideck.platform import find_psmux

    psmux = find_psmux()
    if not psmux:
        return []
    for name in names:
        subprocess.run([psmux, "-L", name, "kill-server"], capture_output=True)
    return list(names)
