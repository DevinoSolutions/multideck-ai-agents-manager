"""The attention daemon command: `multideck attention` (foreground),
`--daemon` (detached, pid file + heartbeat, shows in `status`), `--stop`.
Named attention_cmd (not "attention") to avoid confusion with
multideck.attention, the engine/renderer subsystem it drives.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import click

from multideck.cli.app import main
from multideck.cli.config_io import _load_config_or_exit
from multideck.cli.spawns import _pid_alive
from multideck.paths import find_config
from multideck.style import style
from multideck.titles import get_leaf_name

_PID_PATH = Path.home() / ".multideck" / "attention.pid"

HEARTBEAT_NAME = "attention"


def daemon_pid() -> int | None:
    """PID of the running attention daemon, or None. Clears a stale pid file."""
    try:
        pid = int(_PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return None
    if _pid_alive(pid):
        return pid
    with contextlib.suppress(OSError):
        _PID_PATH.unlink()
    return None


def _write_pid() -> None:
    _PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PID_PATH.write_text(str(os.getpid()))


def _clear_pid() -> None:
    with contextlib.suppress(OSError):
        if _PID_PATH.read_text().strip() == str(os.getpid()):
            _PID_PATH.unlink()


def stop_daemon() -> bool:
    """Stop the attention daemon; True only if a kill was issued and the
    process is confirmed gone. On failure the pid file is kept so `status`
    keeps reporting the truth."""
    pid = daemon_pid()
    if not pid:
        return False
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False
        )
        killed = result.returncode == 0
    else:
        try:
            os.kill(pid, 15)  # SIGTERM
            killed = True
        except OSError:
            killed = False
    if killed and not _pid_alive(pid):
        with contextlib.suppress(OSError):
            _PID_PATH.unlink()
        return True
    return killed and not _pid_alive(pid)


def _name_pairs(config_file: Path) -> list[tuple[str, str]]:
    """(display name, resolved path) for every enabled project."""
    from multideck.launch import _resolve_path  # heavy subsystem: in-body per policy

    cfg = _load_config_or_exit(config_file)
    pairs: list[tuple[str, str]] = []
    for proj in cfg.projects:
        if not proj.enabled:
            continue
        resolved = _resolve_path(proj.path, cfg.base_dir) or proj.path
        pairs.append((proj.title or get_leaf_name(proj.path), resolved))
    return pairs


@main.command("attention")
@click.option("--daemon", "-d", "as_daemon", is_flag=True, help="Run detached")
@click.option("--stop", "do_stop", is_flag=True, help="Stop the running daemon")
@click.option("--interval", default=2.0, show_default=True, help="Poll seconds")
@click.option("--ticks", default=None, type=int, hidden=True)  # test seam
@click.pass_context
def attention_cmd(
    ctx: click.Context,
    as_daemon: bool,
    do_stop: bool,
    interval: float,
    ticks: int | None,
) -> None:
    """Ambient attention signals for your agent fleet.

    Badges every md: window title with its session state, flashes the taskbar
    when an agent needs input or errors, and (when enabled in config) sends a
    Windows toast and/or an ntfy push. States come from the agent-state store
    that Claude Code hooks / Codex notify already write.
    """
    if do_stop:
        if stop_daemon():
            click.echo(f"  {style('+', fg='green')} Stopped the attention daemon.")
        else:
            click.echo(f"  {style('-', dim=True)} Attention daemon was not running.")
        return

    config_path = ctx.obj.get("config_path")
    config_file = find_config(config_path)

    if as_daemon:
        existing = daemon_pid()
        if existing:
            click.echo(
                f"  {style('+', fg='green')} Attention daemon already running "
                f"{style(f'(pid {existing})', dim=True)}"
            )
            return
        args = [sys.executable, "-m", "multideck"]
        if config_path:
            args += ["--config", str(config_path)]
        args += ["attention", "--interval", str(interval)]
        from multideck.launch import (  # heavy subsystem: in-body per policy
            spawn_detached,
        )

        spawn_detached(args)
        for _ in range(20):
            time.sleep(0.1)
            pid = daemon_pid()
            if pid:
                click.echo(
                    f"  {style('+', fg='green')} Attention daemon running "
                    f"{style(f'(pid {pid})', dim=True)}"
                )
                return
        click.echo(f"  {style('x', fg='red')} attention daemon failed to start")
        sys.exit(1)

    # Foreground loop (also the body of the detached child).
    from multideck import attention  # heavy subsystem: in-body per policy
    from multideck.env import get_env  # heavy subsystem: in-body per policy
    from multideck.log import (  # heavy subsystem: in-body per policy
        get_logger,
        write_heartbeat,
    )
    from multideck.platform import get_platform  # heavy subsystem: in-body per policy

    cfg = _load_config_or_exit(config_file)
    att_cfg = cfg.settings.attention
    plat = get_platform()
    engine = attention.AttentionEngine(
        attention.name_map_from_projects(_name_pairs(config_file))
    )

    renderers: list[attention.Renderer] = []
    if plat.supports_attention_signals():
        if att_cfg.badge:
            renderers.append(attention.BadgeRenderer(plat))
        if att_cfg.flash:
            renderers.append(attention.FlashRenderer(plat))
    elif att_cfg.badge or att_cfg.flash:
        click.echo(
            f"  {style('!', fg='yellow')} window badges/flash aren't supported on this OS"
        )
    if att_cfg.toast:
        renderers.append(attention.ToastRenderer(engine))
    if att_cfg.ntfy:
        topic = get_env().ntfy_topic
        if topic:
            renderers.append(attention.NtfyRenderer(engine, str(topic)))
        else:
            click.echo(
                f"  {style('!', fg='yellow')} attention.ntfy is on but "
                "MULTIDECK_NTFY_TOPIC is not set (see .env.example)"
            )
    if not renderers:
        click.echo(
            f"  {style('x', fg='red')} nothing to do: every attention renderer "
            "is disabled or unsupported here"
        )
        sys.exit(1)

    log = get_logger("attention")
    log.info("attention loop starting: %d renderer(s)", len(renderers))
    click.echo(
        f"  {style('#', fg='cyan')} Watching {style(str(len(engine.poll())), bold=True)}"
        f" session(s) — Ctrl+C to stop."
    )
    _write_pid()
    try:
        attention.run_attention_loop(
            engine,
            renderers,
            poll_interval=interval,
            max_ticks=ticks,
            on_tick=lambda _views: write_heartbeat(HEARTBEAT_NAME),
        )
    except KeyboardInterrupt:
        click.echo(f"\n  {style('Stopped.', dim=True)}")
    finally:
        _clear_pid()
