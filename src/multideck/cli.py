from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from multideck import __version__
from multideck.config import load_config
from multideck.init_config import generate_config, write_config


def _find_config(config_arg: str | None) -> str:
    if config_arg:
        return config_arg
    cwd = Path.cwd()
    candidates = [
        cwd / "multideck.config.json",
        cwd / "scripts" / "multideck.config.json",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[0])


def _show_menu(groups: list[str]) -> dict:
    while True:
        click.echo("")
        click.echo("  multideck")
        click.echo("  =========")
        click.echo("   1) Launch missing + tile new windows   (default)")
        click.echo("   2) Re-tile ALL open windows")
        if groups:
            click.echo(f"   3) Launch a group   ({', '.join(groups)})")
        click.echo("   4) Dry run (preview, change nothing)")
        click.echo("   5) Re-generate config from a folder scan")
        click.echo("   Q) Quit")

        choice = click.prompt("  Choose", default="1", show_default=False).strip().lower()

        if choice == "1":
            return {"action": "run", "retile_all": False, "dry_run": False, "group": None}
        elif choice == "2":
            return {"action": "run", "retile_all": True, "dry_run": False, "group": None}
        elif choice == "3" and groups:
            for i, g in enumerate(groups, 1):
                click.echo(f"   {i}) {g}")
            idx_str = click.prompt("  Group number", default="1")
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(groups):
                    return {"action": "run", "retile_all": False, "dry_run": False, "group": groups[idx]}
            except ValueError:
                pass
            click.echo("  Invalid choice.", err=True)
        elif choice == "4":
            return {"action": "run", "retile_all": False, "dry_run": True, "group": None}
        elif choice == "5":
            return {"action": "init"}
        elif choice == "q":
            return {"action": "quit"}
        else:
            click.echo("  Unrecognized choice.", err=True)


@click.command()
@click.option("--go", is_flag=True, help="Skip interactive menu, launch + tile")
@click.option("--retile-all", is_flag=True, help="Re-tile every matching window")
@click.option("--dry-run", is_flag=True, help="Preview plan without launching or moving")
@click.option("-g", "--group", default=None, help="Launch only projects in this group")
@click.option("--init", "do_init", is_flag=True, help="Generate config by scanning a folder")
@click.option("--base-dir", default=None, type=click.Path(), help="Folder to scan with --init")
@click.option("--config", "config_path", default=None, type=click.Path(), help="Path to config file")
@click.option("--force", is_flag=True, help="With --init, overwrite existing config")
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
) -> None:
    """Open every project in its own terminal and auto-tile across all monitors."""
    config_file = _find_config(config_path)

    if do_init:
        if not base_dir:
            base_dir = click.prompt("Base folder to scan for projects")
        if not base_dir:
            click.echo("No base folder given.", err=True)
            sys.exit(1)
        root = Path(base_dir).resolve()
        if not root.is_dir():
            click.echo(f"Folder not found: {base_dir}", err=True)
            sys.exit(1)
        projects = generate_config(str(root))["projects"]
        click.echo(f"Found {len(projects)} project(s).")
        if dry_run:
            click.echo("(dry run — not written)")
            for p in projects:
                click.echo(f"  {p['path']}")
            return
        success = write_config(str(root), config_file, force=force)
        if success:
            click.echo(f"Wrote config to {config_file}")
        else:
            click.echo(f"{config_file} exists — use --force to overwrite.", err=True)
            sys.exit(1)
        return

    if not Path(config_file).exists():
        if sys.stdin.isatty():
            click.echo(f"No config found at: {config_file}")
            base = click.prompt("Enter a base folder to scan (blank to cancel)", default="", show_default=False)
            if base:
                write_config(base.strip(), config_file)
                click.echo(f"Wrote config to {config_file}")
            else:
                sys.exit(1)
        else:
            click.echo(f"No config found at: {config_file}", err=True)
            click.echo("Run:  multideck --init --base-dir <folder>", err=True)
            sys.exit(1)

    try:
        cfg = load_config(config_file)
    except (ValueError, FileNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    has_directive = go or retile_all or dry_run or group
    if not has_directive and sys.stdin.isatty():
        groups = sorted({p.group for p in cfg.projects if p.group})
        menu = _show_menu(list(groups))
        if menu["action"] == "quit":
            click.echo("Bye.")
            return
        if menu["action"] == "init":
            base = click.prompt("Base folder to scan", default="")
            if base:
                write_config(base.strip(), config_file)
                click.echo("Re-run multideck to use the new config.")
            return
        retile_all = menu["retile_all"]
        dry_run = menu["dry_run"]
        group = menu.get("group")

    from multideck.launch import run_multideck, RunOpts
    run_multideck(cfg, RunOpts(
        retile_all=retile_all,
        dry_run=dry_run,
        group=group,
        config_path=config_file,
    ))
