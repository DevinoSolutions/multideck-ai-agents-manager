from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import click

from multideck.config import MultideckConfig, ProjectConfig
from multideck.grid import compute_grid, Rect
from multideck.platform import Platform, PsmuxWindowOpts, TerminalLaunchOpts, VSCodeLaunchOpts, get_platform
from multideck.sessions import build_resume_command
from multideck.sessions.claude import encode_claude_project_path, get_claude_session_ids
from multideck.sessions.codex import get_codex_session_ids
from multideck.titles import generate_titles, get_leaf_name


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
    if tool == "claude":
        return get_claude_session_ids(project_dir, count)
    if tool == "codex":
        return get_codex_session_ids(project_dir, count)
    return [None] * count


HAPPY_AGENTS = {"claude", "codex"}

S = click.style


def _psmux_session_name(title: str) -> str:
    """Sanitize a window title into a valid psmux/tmux session name."""
    return title.replace(".", "-").replace(":", "-").replace(" ", "-")


def _wrap_happy(tool: str, cmd: str) -> str:
    """Wrap a CLI agent command with Happy for mobile/web access."""
    if tool in HAPPY_AGENTS:
        return f"happy {cmd}"
    return cmd


def run_multideck(config: MultideckConfig, opts: RunOpts) -> None:
    plat = get_platform()
    plat.set_dpi_aware()

    monitors = plat.list_monitors()
    if not monitors:
        click.echo(f"  {S('✗', fg='red')} No monitors detected.", err=True)
        return

    slots = compute_grid(monitors, config.layout.columns, config.layout.rows)
    per_screen = config.layout.columns * config.layout.rows

    grid_label = f"{config.layout.columns}x{config.layout.rows}"
    click.echo(
        f"\n  {S('#', fg='cyan')} {S(str(len(monitors)), fg='cyan', bold=True)} screen(s)  "
        f"{S('->', dim=True)}  {S(str(len(slots)), fg='green', bold=True)} tile slots  "
        f"{S(f'({grid_label} per screen)', dim=True)}"
    )
    if opts.dry_run:
        click.echo(f"  {S('! DRY RUN', fg='yellow', bold=True)} {S('-- nothing will be launched or moved.', dim=True)}\n")

    base_dir = config.base_dir
    if base_dir:
        base_dir = os.path.expandvars(os.path.expanduser(base_dir)).replace("/", os.sep)

    projects = [p for p in config.projects if p.enabled]
    if opts.group:
        projects = [p for p in projects if p.group and p.group.lower() == opts.group.lower()]
        if not projects:
            groups = sorted({p.group for p in config.projects if p.group})
            click.echo(f"No projects in group '{opts.group}'. Available: {', '.join(groups)}", err=True)
            return
        click.echo(f"Group '{opts.group}': {len(projects)} project(s)")

    has_remote = any(p.host for p in projects)
    if has_remote and not shutil.which("ssh"):
        click.echo(S("  ! Remote projects configured but 'ssh' not on PATH.", fg="yellow"))

    targets: list[_Target] = []
    new_count = 0
    tools = config.settings.tools
    use_psmux = config.settings.psmux and sys.platform == "win32"
    psmux_windows: list[PsmuxWindowOpts] = []
    _psmux_colors: dict[str, str | None] = {}

    for proj in projects:
        tool = proj.tool or config.settings.default_tool
        is_remote = bool(proj.host)

        if tool in ("code", "vscode", "cursor"):
            key = get_leaf_name(proj.remote_path or proj.path) if is_remote else get_leaf_name(proj.path)
            name = proj.title or key
            running = plat.find_window(key, mode="contains") is not None
            if not running and not opts.dry_run:
                vsc_dir = proj.remote_path or proj.path if is_remote else (_resolve_path(proj.path, base_dir) or proj.path)
                ide_cmd = "cursor" if tool == "cursor" else "code"
                plat.launch_vscode(VSCodeLaunchOpts(
                    dir=vsc_dir,
                    ssh_host=proj.host if is_remote else None,
                    command=ide_cmd,
                ))
                time.sleep(config.settings.launch_delay_ms / 1000)
            if not running:
                new_count += 1
            targets.append(_Target(name=name, key=key, mode="contains", is_new=not running))
            _log_project(name, tool, running, proj.host, happy=False)
            continue

        windows_cfg = proj.windows
        if is_remote or tool in ("code", "vscode", "cursor"):
            windows_cfg = None
        titles = generate_titles(proj.title, proj.path, windows_cfg)
        window_count = len(titles)

        session_ids: list[str | None] = [None] * window_count
        if window_count > 1 and tool in ("claude", "codex") and not is_remote:
            resolved_dir = _resolve_path(proj.path, base_dir)
            if resolved_dir:
                session_ids = _get_session_ids(tool, resolved_dir, window_count)

        base_cmd = tools.get(tool)
        if not base_cmd:
            click.echo(f"SKIP: {titles[0]} — unknown tool '{tool}' (add under settings.tools)")
            continue

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
                    _psmux_colors[wname] = proj.color
            running = plat.find_window(win_title, mode="exact") is not None
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

    if psmux_windows and not opts.dry_run:
        plat.launch_psmux_session(psmux_windows)
        for pw in psmux_windows:
            plat.attach_psmux(pw.window_name, pw.window_name,
                              _psmux_colors.get(pw.window_name))
            time.sleep(config.settings.launch_delay_ms / 1000)
        click.echo(f"\n  {S('#', fg='yellow')} psmux: {S(str(len(psmux_windows)), fg='yellow', bold=True)} sessions"
                    f" {S('(synced with mobile)', dim=True)}")
        click.echo(f"  {S('From SSH:', dim=True)} {S('psmux -L <name> attach', fg='cyan')}"
                    f" {S('or', dim=True)} {S('multideck sessions', fg='cyan')}")

    to_place = targets if opts.retile_all else [t for t in targets if t.is_new]

    if not to_place:
        click.echo(f"\n  {S('+', fg='green')} All windows already positioned.")
        return

    mode_label = S(" retile all", fg="yellow") if opts.retile_all else (S(" dry run", fg="yellow") if opts.dry_run else "")
    click.echo(f"\n  {S('#', fg='cyan')} Tiling {S(str(len(to_place)), fg='cyan', bold=True)} window(s)...{mode_label}")

    if not opts.dry_run and new_count > 0:
        time.sleep(config.settings.settle_seconds)

    for slot_idx, target in enumerate(to_place):
        pos = slots[slot_idx % len(slots)]
        screen_num = (slot_idx % len(slots)) // per_screen + 1

        if opts.dry_run:
            dims = S(f"{pos.w}x{pos.h}", dim=True)
            at = S(f"({pos.x},{pos.y})", dim=True)
            click.echo(f"    {S('>', fg='cyan')} {target.name:<28} {S('->', dim=True)} screen {screen_num}  {dims} {at}")
            continue

        handle = plat.find_window(target.key, mode=target.mode)
        if handle is None and target.is_new:
            deadline = 20 if target.mode == "contains" else 6
            for _ in range(deadline):
                time.sleep(1)
                handle = plat.find_window(target.key, mode=target.mode)
                if handle is not None:
                    break

        if handle is not None:
            plat.move_window(handle, Rect(x=pos.x, y=pos.y, w=pos.w, h=pos.h))
            click.echo(f"    {S('+', fg='green')} {target.name} {S('->', dim=True)} screen {screen_num}")
        else:
            click.echo(f"    {S('x', fg='red')} {target.name} {S('not found', dim=True)}")

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
