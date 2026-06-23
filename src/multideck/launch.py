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
from multideck.platform import Platform, TerminalLaunchOpts, VSCodeLaunchOpts, get_platform
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


def run_multideck(config: MultideckConfig, opts: RunOpts) -> None:
    plat = get_platform()
    plat.set_dpi_aware()

    monitors = plat.list_monitors()
    if not monitors:
        click.echo("No monitors detected.", err=True)
        return

    slots = compute_grid(monitors, config.layout.columns, config.layout.rows)
    per_screen = config.layout.columns * config.layout.rows

    click.echo(
        f"Detected {len(monitors)} screen(s) -> {len(slots)} tile slot(s) "
        f"({config.layout.columns} x {config.layout.rows} per screen)"
    )
    if opts.dry_run:
        click.echo("DRY RUN — nothing will be launched or moved.\n")

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
        click.echo("WARNING: remote projects configured but 'ssh' not on PATH.")

    targets: list[_Target] = []
    new_count = 0
    tools = config.settings.tools

    for proj in projects:
        tool = proj.tool or config.settings.default_tool
        is_remote = bool(proj.host)

        if tool == "code":
            key = get_leaf_name(proj.remote_path or proj.path) if is_remote else get_leaf_name(proj.path)
            name = proj.title or key
            running = plat.find_window(key, mode="contains") is not None
            if not running and not opts.dry_run:
                vsc_dir = proj.remote_path or proj.path if is_remote else (_resolve_path(proj.path, base_dir) or proj.path)
                plat.launch_vscode(VSCodeLaunchOpts(
                    dir=vsc_dir,
                    ssh_host=proj.host if is_remote else None,
                ))
                time.sleep(config.settings.launch_delay_ms / 1000)
            if not running:
                new_count += 1
            targets.append(_Target(name=name, key=key, mode="contains", is_new=not running))
            _log_project(name, tool, running, proj.host)
            continue

        windows_cfg = proj.windows
        if is_remote or tool == "code":
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

        for i, win_title in enumerate(titles):
            if window_count > 1 and session_ids[i] is not None:
                cmd = build_resume_command(tool, base_cmd, session_ids[i])
            elif window_count > 1:
                cmd = build_resume_command(tool, base_cmd, None)
            else:
                cmd = base_cmd

            running = plat.find_window(win_title, mode="exact") is not None
            if not running and not opts.dry_run:
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
                time.sleep(config.settings.launch_delay_ms / 1000)
            if not running:
                new_count += 1
            targets.append(_Target(name=win_title, key=win_title, mode="exact", is_new=not running))
            _log_project(win_title, tool, running, proj.host)

    to_place = targets if opts.retile_all else [t for t in targets if t.is_new]

    if not to_place:
        click.echo("\nNothing to position.")
        return

    label = " [retile all]" if opts.retile_all else (" [dry run]" if opts.dry_run else "")
    click.echo(f"\nTiling {len(to_place)} window(s){label}...")

    if not opts.dry_run and new_count > 0:
        time.sleep(config.settings.settle_seconds)

    for slot_idx, target in enumerate(to_place):
        pos = slots[slot_idx % len(slots)]
        screen_num = (slot_idx % len(slots)) // per_screen + 1

        if opts.dry_run:
            click.echo(f"  {target.name:<30} -> screen {screen_num} {pos.label}   {pos.w}x{pos.h} @ ({pos.x},{pos.y})")
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
            click.echo(f"  {target.name} -> screen {screen_num} {pos.label}")
        else:
            click.echo(f"  Not found: {target.name}")

    click.echo("\nDone!")


def _log_project(name: str, tool: str, running: bool, host: str | None) -> None:
    status = "OPEN:" if running else "NEW: "
    loc = f" @ {host}" if host else ""
    click.echo(f"{status} {name} [{tool}{loc}]")
