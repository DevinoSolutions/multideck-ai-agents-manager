from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from multideck import __version__
from multideck.config import load_config
from multideck.init_config import write_config


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
    if static.exists():
        return static
    return static


def _styled(text: str, **kwargs) -> str:
    return click.style(text, **kwargs)


def _header() -> None:
    click.echo()
    click.echo(f"  {_styled('multideck', bold=True)}  {_styled(f'v{__version__}', dim=True)}")
    click.echo(f"  {_styled('─' * 36, dim=True)}")


def _show_menu(groups: list[str]) -> dict:
    while True:
        _header()
        click.echo()
        click.echo(f"  {_styled('[1]', fg='cyan')}  Launch & tile new windows")
        click.echo(f"  {_styled('[2]', fg='cyan')}  Re-tile all open windows")
        if groups:
            group_list = _styled(', '.join(groups), dim=True)
            click.echo(f"  {_styled('[3]', fg='cyan')}  Launch a group  {_styled('→', dim=True)}  {group_list}")
        click.echo(f"  {_styled('[e]', fg='yellow')}  Edit config")
        click.echo(f"  {_styled('[q]', fg='red')}  Quit")
        click.echo()

        choice = click.prompt(f"  {_styled('>', fg='green', bold=True)}", default="1", show_default=False, prompt_suffix=" ").strip().lower()

        if choice == "1":
            return {"action": "run", "retile_all": False, "group": None}
        elif choice == "2":
            return {"action": "run", "retile_all": True, "group": None}
        elif choice == "3" and groups:
            click.echo()
            for i, g in enumerate(groups, 1):
                click.echo(f"    {_styled(str(i), fg='cyan')}  {g}")
            click.echo()
            idx_str = click.prompt(f"  {_styled('group', fg='green')}", default="1", show_default=False, prompt_suffix=" ").strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(groups):
                    return {"action": "run", "retile_all": False, "group": groups[idx]}
            except ValueError:
                pass
            click.echo(f"  {_styled('Invalid choice.', fg='red')}")
        elif choice == "e":
            return {"action": "edit"}
        elif choice == "q":
            return {"action": "quit"}
        else:
            click.echo(f"  {_styled('Invalid choice.', fg='red')}")


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
    """Scan Claude/Codex history to auto-generate a config. Returns True if config was written."""
    from multideck.discover import discover_projects, projects_to_config

    click.echo()
    click.echo(f"  {_styled('No config found.', fg='yellow')} Scanning your recent projects...")
    click.echo()

    projects = discover_projects()

    if not projects:
        click.echo(f"  {_styled('No projects found', dim=True)} in Claude or Codex history.")
        click.echo(f"  Create a config manually at: {_styled(str(config_file), bold=True)}")
        return False

    click.echo(f"  Found {_styled(str(len(projects)), fg='green', bold=True)} projects from your session history:\n")

    for i, p in enumerate(projects):
        leaf = Path(p["path"]).name
        tool_badge = _styled(f"[{p['tool']}]", fg='cyan', dim=True)
        sessions = _styled(f"{p['session_count']} sessions", dim=True)
        click.echo(f"    {_styled(str(i + 1).rjust(2), dim=True)}  {leaf:<30} {tool_badge}  {sessions}")

    click.echo()
    if not click.confirm(f"  Generate config with these {len(projects)} projects?", default=True):
        click.echo(f"\n  {_styled('Cancelled.', dim=True)}")
        return False

    config = projects_to_config(projects)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

    click.echo(f"\n  {_styled('✓', fg='green', bold=True)} Config saved to {_styled(str(config_file), bold=True)}")

    if click.confirm("  Open in your editor?", default=False):
        _open_in_editor(config_file)

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
        if sys.stdin.isatty():
            wrote = _run_discovery(config_file)
            if not wrote:
                sys.exit(1)
        else:
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
