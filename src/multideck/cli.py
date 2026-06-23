from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from multideck import __version__
from multideck.config import load_config
from multideck.init_config import write_config

S = click.style


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "multideck"


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _find_config(config_arg: str | None) -> Path:
    if config_arg:
        return Path(config_arg)
    cwd = Path.cwd()
    for name in ("multideck.config.json",):
        for loc in (cwd, cwd / "scripts"):
            if (loc / name).exists():
                return loc / name
    static = _config_path()
    return static


LOGO_LINES = [
    r"           _ _   _    _        _   ",
    r" _ __ _  _| | |_(_)__| |___ __| |__",
    r"| '  \ || | |  _| / _` / -_) _| / /",
    r"|_|_|_\_,_|_|\__|_\__,_\___\__|_\_\\",
]


def _banner() -> None:
    click.echo()
    for line in LOGO_LINES:
        click.echo(f"  {S(line, fg='cyan')}")
    click.echo(f"  {S(f'v{__version__}', dim=True)}  {S('auto-tile your AI workspace', dim=True)}")
    click.echo()


def _divider() -> None:
    click.echo(f"  {S('-' * 40, dim=True)}")


def _menu_item(key: str, label: str, key_fg: str = "cyan", extra: str = "") -> None:
    click.echo(f"   {S(key, fg=key_fg, bold=True)}   {label}{extra}")


def _show_menu(groups: list[str]) -> dict:
    while True:
        _banner()
        _divider()
        click.echo()
        _menu_item("1", "Launch & tile new windows", extra=S("  (default)", dim=True))
        _menu_item("2", "Re-tile all open windows")
        if groups:
            group_list = S(f"  {' | '.join(groups)}", dim=True)
            _menu_item("3", "Launch a group" + group_list)
        _menu_item("e", "Edit config", key_fg="yellow")
        _menu_item("q", "Quit", key_fg="red")
        click.echo()

        choice = click.prompt(
            f"  {S('>', fg='cyan', bold=True)}",
            default="1", show_default=False, prompt_suffix=" ",
        ).strip().lower()

        if choice == "1":
            return {"action": "run", "retile_all": False, "group": None}
        elif choice == "2":
            return {"action": "run", "retile_all": True, "group": None}
        elif choice == "3" and groups:
            click.echo()
            for i, g in enumerate(groups, 1):
                _menu_item(str(i), g)
            click.echo()
            idx_str = click.prompt(
                f"  {S('group', fg='cyan')}",
                default="1", show_default=False, prompt_suffix=" ",
            ).strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(groups):
                    return {"action": "run", "retile_all": False, "group": groups[idx]}
            except ValueError:
                pass
            click.echo(f"\n  {S('x', fg='red')} Invalid choice.\n")
        elif choice == "e":
            return {"action": "edit"}
        elif choice == "q":
            return {"action": "quit"}
        else:
            click.echo(f"\n  {S('x', fg='red')} Invalid choice.\n")


def _open_in_editor(path: Path) -> None:
    path_str = str(path)
    if sys.platform == "win32":
        os.startfile(path_str)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", path_str])
    else:
        import subprocess
        editor = os.environ.get("EDITOR", "xdg-open")
        subprocess.Popen([editor, path_str])


def _run_discovery(config_file: Path) -> bool:
    from multideck.discover import discover_projects, projects_to_config

    _banner()
    click.echo(f"  {S('Welcome!', fg='green', bold=True)} multideck opens a terminal for each of your")
    click.echo(f"  projects, launches your AI agent inside it, and tiles")
    click.echo(f"  all windows neatly across your screens.")
    click.echo()
    click.echo(f"  Scanning your recent sessions to find your projects...")
    click.echo()

    projects, days = discover_projects()

    if not projects:
        click.echo(f"  {S('No projects found', dim=True)} in Claude, Codex, or VS Code history.")
        click.echo(f"  Create a config manually at: {S(str(config_file), bold=True)}")
        return False

    click.echo(f"  Found {S(str(len(projects)), fg='green', bold=True)} projects from the last {days} days:\n")

    tool_colors = {"claude": "magenta", "codex": "cyan", "vscode": "blue"}
    for i, p in enumerate(projects):
        leaf = Path(p["path"]).name
        tc = tool_colors.get(p["tool"], "white")
        badge = S(f"[{p['tool']}]", fg=tc, dim=True)
        num = S(f"{i + 1:>2}", dim=True)
        click.echo(f"   {num}  {leaf:<34} {badge}")

    click.echo()
    _divider()
    click.echo()

    if not click.confirm(f"  Generate config with these {len(projects)} projects?", default=True):
        click.echo(f"\n  {S('Cancelled.', dim=True)}")
        return False

    config = projects_to_config(projects)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

    click.echo(f"\n  {S('+', fg='green', bold=True)} Saved to {S(str(config_file), fg='cyan')}")
    click.echo()
    click.echo(f"  Run {S('multideck', bold=True)} again to launch all your projects")
    click.echo(f"  and tile them across your screens.")
    click.echo()
    click.echo(f"  To tweak the config: {S('multideck --edit', fg='cyan')}")
    click.echo()

    return True


@click.command()
@click.option("--go", is_flag=True, help="Skip interactive menu, launch + tile")
@click.option("--retile-all", is_flag=True, help="Re-tile every matching window")
@click.option("--dry-run", is_flag=True, hidden=True)
@click.option("-g", "--group", default=None, help="Launch only projects in this group")
@click.option("--init", "do_init", is_flag=True, help="Re-scan and regenerate config")
@click.option("--base-dir", default=None, type=click.Path(), help="Folder to scan with --init")
@click.option("--config", "config_path", default=None, type=click.Path(), help="Path to config file")
@click.option("--force", is_flag=True, help="With --init, overwrite existing config")
@click.option("--edit", "do_edit", is_flag=True, help="Open config in your default editor")
@click.version_option(__version__)
def main(
    go: bool,
    retile_all: bool,
    dry_run: bool,
    group: str | None,
    do_init: bool,
    base_dir: str | None,
    config_path: str | None,
    force: bool,
    do_edit: bool,
) -> None:
    """Open every project in its own terminal and auto-tile across all monitors."""
    config_file = _find_config(config_path)

    if do_edit:
        if not config_file.exists():
            click.echo(f"No config at {config_file}. Run multideck first to generate one.")
            sys.exit(1)
        _open_in_editor(config_file)
        return

    if do_init:
        if base_dir:
            root = Path(base_dir).resolve()
            if not root.is_dir():
                click.echo(f"Folder not found: {base_dir}", err=True)
                sys.exit(1)
            success = write_config(str(root), str(config_file), force=force)
            if success:
                click.echo(f"Wrote config to {config_file}")
            else:
                click.echo(f"{config_file} exists — use --force to overwrite.", err=True)
                sys.exit(1)
        else:
            if config_file.exists() and not force:
                click.echo(f"{config_file} exists — use --force to overwrite.", err=True)
                sys.exit(1)
            _run_discovery(config_file)
        return

    if not config_file.exists():
        if config_path:
            click.echo(f"No config found at: {config_file}", err=True)
            sys.exit(1)
        if sys.stdin.isatty() and not go:
            wrote = _run_discovery(config_file)
            if not wrote:
                sys.exit(1)
        elif not config_file.exists():
            click.echo(f"No config found. Run: multideck --init", err=True)
            sys.exit(1)

    try:
        cfg = load_config(str(config_file))
    except (ValueError, FileNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    has_directive = go or retile_all or dry_run or group
    if not has_directive and sys.stdin.isatty():
        groups = sorted({p.group for p in cfg.projects if p.group})
        menu = _show_menu(list(groups))
        if menu["action"] == "quit":
            return
        if menu["action"] == "edit":
            _open_in_editor(config_file)
            return
        retile_all = menu["retile_all"]
        group = menu.get("group")

    from multideck.launch import run_multideck, RunOpts
    run_multideck(cfg, RunOpts(
        retile_all=retile_all,
        dry_run=dry_run,
        group=group,
        config_path=str(config_file),
    ))
