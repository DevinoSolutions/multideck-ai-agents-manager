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

LOGO_LINES = [
    r"           _ _   _    _        _   ",
    r" _ __ _  _| | |_(_)__| |___ __| |__",
    r"| '  \ || | |  _| / _` / -_) _| / /",
    r"|_|_|_\_,_|_|\__|_\__,_\___\__|_\_\\",
]


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
    return _config_path()


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


def _load_raw_config(path: Path) -> dict:
    if not path.exists():
        click.echo(f"No config found at: {path}", err=True)
        click.echo(f"Run {S('multideck', bold=True)} to generate one.", err=True)
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def _save_raw_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    click.echo(f"  {S('+', fg='green', bold=True)} Saved.")


def _config_menu(config_file: Path) -> None:
    """Interactive config editor accessed from the main menu."""
    while True:
        data = _load_raw_config(config_file)
        layout = data.get("layout", {})
        settings = data.get("settings", {})
        projects = data.get("projects", [])
        tools = settings.get("tools", {})
        cols, rows = layout.get("columns", 2), layout.get("rows", 1)
        dtool = settings.get("defaultTool", "claude")
        total_slots = cols * rows

        click.echo()
        click.echo(f"  {S('Settings', bold=True)}")
        _divider()
        click.echo()
        _menu_item("1", f"Window grid      {S(f'{cols} cols x {rows} rows', fg='green')}"
                   f"  {S(f'= {total_slots} windows per screen', dim=True)}")
        _menu_item("2", f"Default AI tool   {S(dtool, fg='green')}"
                   f"  {S('-- launched in each project', dim=True)}")
        base = data.get("baseDir")
        if base:
            short = base if len(base) <= 35 else "..." + base[-32:]
            _menu_item("3", f"Projects folder   {S(short, fg='green')}")
        else:
            _menu_item("3", f"Projects folder   {S('(not set -- using absolute paths)', dim=True)}")
        _menu_item("4", f"Tool commands     {S(', '.join(tools.keys()) or '(none)', dim=True)}"
                   f"  {S('-- what runs in the terminal', dim=True)}")
        click.echo()
        click.echo(f"  {S('Projects', bold=True)}")
        _divider()
        click.echo()
        _menu_item("5", f"Add a project     {S('-- register a new folder', dim=True)}")
        _menu_item("6", f"Remove a project  {S(f'({len(projects)} configured)', dim=True)}")
        click.echo()
        _menu_item("7", f"Open config file in editor", key_fg="green")
        _menu_item("b", "Back to main menu", key_fg="yellow")
        click.echo()

        choice = click.prompt(f"  {S('>', fg='cyan', bold=True)}", default="b", show_default=False, prompt_suffix=" ").strip().lower()

        if choice == "1":
            click.echo()
            click.echo(f"  {S('How many windows per screen?', bold=True)}")
            click.echo(f"  {S('Columns = side by side, Rows = stacked.', dim=True)}")
            click.echo(f"  {S('Example: 2 cols x 1 row = two windows side by side.', dim=True)}")
            click.echo()
            new_cols = click.prompt(f"  Columns (side by side)", default=cols, type=int)
            new_rows = click.prompt(f"  Rows (stacked)", default=rows, type=int)
            new_cols, new_rows = max(1, new_cols), max(1, new_rows)
            data.setdefault("layout", {})
            data["layout"]["columns"] = new_cols
            data["layout"]["rows"] = new_rows
            _save_raw_config(config_file, data)
            click.echo(f"  {S('+', fg='green')} {new_cols * new_rows} windows per screen ({new_cols} x {new_rows})")

        elif choice == "2":
            click.echo()
            click.echo(f"  {S('Which AI tool should open in each project by default?', bold=True)}")
            click.echo(f"  {S('Individual projects can override this.', dim=True)}")
            click.echo()
            available = list(tools.keys()) or ["claude", "codex"]
            for i, t in enumerate(available, 1):
                marker = S(" <-- current", dim=True) if t == dtool else ""
                _menu_item(str(i), f"{t}{marker}")
            click.echo()
            idx_str = click.prompt(f"  Pick a number or type a name", default=dtool, show_default=False).strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(available):
                    idx_str = available[idx]
            except ValueError:
                pass
            data.setdefault("settings", {})
            data["settings"]["defaultTool"] = idx_str
            _save_raw_config(config_file, data)

        elif choice == "3":
            click.echo()
            click.echo(f"  {S('Where are your projects?', bold=True)}")
            click.echo(f"  {S('Project paths in your config are relative to this folder.', dim=True)}")
            click.echo(f"  {S('Example: if base is C:/projects and a project path is', dim=True)}")
            click.echo(f"  {S('api/backend, it opens C:/projects/api/backend.', dim=True)}")
            click.echo()
            new_dir = click.prompt(f"  Projects folder", default=data.get("baseDir", "")).strip()
            if new_dir:
                data["baseDir"] = new_dir.replace("\\", "/")
                _save_raw_config(config_file, data)

        elif choice == "4":
            _tools_menu(config_file, data)

        elif choice == "5":
            click.echo()
            click.echo(f"  {S('Add a project folder for multideck to open.', bold=True)}")
            click.echo(f"  {S('Path can be absolute or relative to your projects folder.', dim=True)}")
            click.echo()
            path = click.prompt(f"  Folder path").strip()
            if not path:
                continue
            entry: dict = {"path": path.replace("\\", "/")}
            click.echo()
            click.echo(f"  {S('Optional settings (press Enter to skip each):', dim=True)}")
            click.echo()
            group = click.prompt(f"  Group {S('-- for launching subsets, e.g. INTERNAL', dim=True)}",
                                 default="", show_default=False).strip()
            if group:
                entry["group"] = group
            tool = click.prompt(f"  Tool  {S('-- override default, e.g. codex, vscode', dim=True)}",
                                default="", show_default=False).strip()
            if tool:
                entry["tool"] = tool
            color = click.prompt(f"  Color {S('-- terminal tab color, e.g. #3b82f6', dim=True)}",
                                 default="", show_default=False).strip()
            if color:
                entry["color"] = color
            data.setdefault("projects", []).append(entry)
            _save_raw_config(config_file, data)
            click.echo(f"  {S('+', fg='green')} Added {S(path, fg='cyan')}")

        elif choice == "6":
            _remove_project_menu(config_file, data)

        elif choice == "7":
            _open_in_editor(config_file)
            return

        elif choice == "b":
            return


def _tools_menu(config_file: Path, data: dict) -> None:
    tools = data.get("settings", {}).get("tools", {})
    while True:
        click.echo()
        click.echo(f"  {S('Tool Commands', bold=True)}")
        click.echo(f"  {S('Each tool name maps to the shell command that runs inside', dim=True)}")
        click.echo(f"  {S('the terminal. e.g. \"claude\" runs \"claude --continue\".', dim=True)}")
        _divider()
        click.echo()
        for name, cmd in tools.items():
            click.echo(f"    {S(name, fg='cyan'):<20} -> {S(cmd, dim=True)}")
        if not tools:
            click.echo(f"    {S('(no tools configured)', dim=True)}")
        click.echo()
        _menu_item("a", "Add or edit a tool")
        _menu_item("r", "Remove a tool")
        _menu_item("b", "Back", key_fg="yellow")
        click.echo()

        choice = click.prompt(f"  {S('>', fg='cyan', bold=True)}", default="b", show_default=False, prompt_suffix=" ").strip().lower()

        if choice == "a":
            click.echo()
            click.echo(f"  {S('Name is a short label (e.g. aider, shell).', dim=True)}")
            click.echo(f"  {S('Command is what runs in the terminal (e.g. aider --model sonnet).', dim=True)}")
            click.echo()
            name = click.prompt(f"  Tool name").strip()
            if not name:
                continue
            existing = tools.get(name, "")
            cmd = click.prompt(f"  Shell command to run", default=existing).strip()
            data.setdefault("settings", {}).setdefault("tools", {})
            data["settings"]["tools"][name] = cmd
            tools = data["settings"]["tools"]
            _save_raw_config(config_file, data)

        elif choice == "r":
            if not tools:
                click.echo(f"  {S('No tools to remove.', dim=True)}")
                continue
            click.echo()
            tool_names = list(tools.keys())
            for i, name in enumerate(tool_names, 1):
                _menu_item(str(i), name)
            click.echo()
            idx_str = click.prompt(f"  Remove which?", default="").strip()
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(tool_names):
                    del tools[tool_names[idx]]
                    _save_raw_config(config_file, data)
            except (ValueError, IndexError):
                click.echo(f"  {S('x', fg='red')} Invalid choice.")

        elif choice == "b":
            return


def _remove_project_menu(config_file: Path, data: dict) -> None:
    projects = data.get("projects", [])
    if not projects:
        click.echo(f"  {S('No projects to remove.', dim=True)}")
        return

    click.echo()
    for i, p in enumerate(projects, 1):
        leaf = Path(p.get("path", "?")).name
        extra = ""
        if p.get("group"):
            extra = f"  {S(p['group'], dim=True)}"
        if not p.get("enabled", True):
            extra += f"  {S('disabled', fg='red')}"
        click.echo(f"   {S(str(i).rjust(2), dim=True)}  {leaf:<30}{extra}")

    click.echo()
    idx_str = click.prompt(f"  Remove which? {S('(number or b to cancel)', dim=True)}", default="b", show_default=False).strip()
    if idx_str.lower() == "b":
        return
    try:
        idx = int(idx_str) - 1
        if 0 <= idx < len(projects):
            removed = projects.pop(idx)
            _save_raw_config(config_file, data)
            click.echo(f"  Removed {S(Path(removed.get('path', '?')).name, fg='cyan')}")
        else:
            click.echo(f"  {S('x', fg='red')} Invalid number.")
    except ValueError:
        click.echo(f"  {S('x', fg='red')} Invalid choice.")


def _show_menu(groups: list[str], config_file: Path | None = None) -> dict:
    config_changed = False
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
            return {"action": "run", "retile_all": False, "group": None, "reload": config_changed}
        elif choice == "2":
            return {"action": "run", "retile_all": True, "group": None, "reload": config_changed}
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
                    return {"action": "run", "retile_all": False, "group": groups[idx], "reload": config_changed}
            except ValueError:
                pass
            click.echo(f"\n  {S('x', fg='red')} Invalid choice.\n")
        elif choice == "e":
            if config_file and config_file.exists():
                _config_menu(config_file)
                data = json.loads(config_file.read_text(encoding="utf-8"))
                projects = data.get("projects", [])
                groups = sorted({p.get("group", "") for p in projects if p.get("group")})
                config_changed = True
            else:
                _open_in_editor(config_file or _config_path())
        elif choice == "q":
            return {"action": "quit", "reload": False}
        else:
            click.echo(f"\n  {S('x', fg='red')} Invalid choice.\n")


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
    click.echo(f"  To tweak the config: {S('multideck config show', fg='cyan')}")
    click.echo()

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
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
@click.pass_context
def main(
    ctx: click.Context,
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
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path

    if ctx.invoked_subcommand is not None:
        return

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
                click.echo(f"{config_file} exists -- use --force to overwrite.", err=True)
                sys.exit(1)
        else:
            if config_file.exists() and not force:
                click.echo(f"{config_file} exists -- use --force to overwrite.", err=True)
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
        menu = _show_menu(list(groups), config_file)
        if menu["action"] == "quit":
            return
        if menu.get("reload"):
            cfg = load_config(str(config_file))
        retile_all = menu["retile_all"]
        group = menu.get("group")

    from multideck.launch import run_multideck, RunOpts
    run_multideck(cfg, RunOpts(
        retile_all=retile_all,
        dry_run=dry_run,
        group=group,
        config_path=str(config_file),
    ))


# ---------------------------------------------------------------------------
# multideck config ...
# ---------------------------------------------------------------------------

@main.group()
@click.pass_context
def config(ctx: click.Context) -> None:
    """View and modify your multideck configuration."""
    pass


@config.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Display current configuration."""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)

    _banner()
    click.echo(f"  {S('Config:', bold=True)} {S(str(config_file), dim=True)}")
    click.echo()

    click.echo(f"  {S('Base dir:', bold=True)}     {data.get('baseDir', S('(not set)', dim=True))}")

    layout = data.get("layout", {})
    cols, rows = layout.get("columns", 2), layout.get("rows", 1)
    click.echo(f"  {S('Layout:', bold=True)}       {cols} x {rows}")

    settings = data.get("settings", {})
    click.echo(f"  {S('Default tool:', bold=True)} {settings.get('defaultTool', 'claude')}")
    click.echo()

    tools = settings.get("tools", {})
    if tools:
        click.echo(f"  {S('Tools:', bold=True)}")
        for name, cmd in tools.items():
            click.echo(f"    {S(name, fg='cyan'):<20} {S(cmd, dim=True)}")
        click.echo()

    projects = data.get("projects", [])
    click.echo(f"  {S('Projects:', bold=True)} {len(projects)}")
    for p in projects:
        path = p.get("path", "?")
        tool = p.get("tool", "")
        group = p.get("group", "")
        enabled = p.get("enabled", True)

        leaf = Path(path).name
        parts = []
        if tool:
            parts.append(S(tool, fg="cyan"))
        if group:
            parts.append(S(group, dim=True))
        if not enabled:
            parts.append(S("disabled", fg="red"))
        extra = f"  {' | '.join(parts)}" if parts else ""
        click.echo(f"    {leaf:<30}{extra}")

    click.echo()


@config.command("layout")
@click.argument("columns", type=int)
@click.argument("rows", type=int)
@click.pass_context
def config_layout(ctx: click.Context, columns: int, rows: int) -> None:
    """Set grid layout. Usage: multideck config layout 3 2"""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    data.setdefault("layout", {})
    data["layout"]["columns"] = max(1, columns)
    data["layout"]["rows"] = max(1, rows)
    _save_raw_config(config_file, data)
    click.echo(f"  Layout set to {columns} x {rows}")


@config.command("base-dir")
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.pass_context
def config_base_dir(ctx: click.Context, path: str) -> None:
    """Set the base directory for project paths."""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    resolved = str(Path(path).resolve()).replace("\\", "/")
    data["baseDir"] = resolved
    _save_raw_config(config_file, data)
    click.echo(f"  Base dir set to {resolved}")


@config.command("default-tool")
@click.argument("tool")
@click.pass_context
def config_default_tool(ctx: click.Context, tool: str) -> None:
    """Set the default tool for new projects."""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    data.setdefault("settings", {})
    data["settings"]["defaultTool"] = tool
    _save_raw_config(config_file, data)
    click.echo(f"  Default tool set to {S(tool, fg='cyan')}")


@config.command("tool")
@click.argument("name")
@click.argument("command")
@click.pass_context
def config_tool(ctx: click.Context, name: str, command: str) -> None:
    """Add or update a tool command. Usage: multideck config tool aider 'aider --model sonnet'"""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    data.setdefault("settings", {}).setdefault("tools", {})
    data["settings"]["tools"][name] = command
    _save_raw_config(config_file, data)
    click.echo(f"  Tool {S(name, fg='cyan')} = {S(command, dim=True)}")


@config.command("remove-tool")
@click.argument("name")
@click.pass_context
def config_remove_tool(ctx: click.Context, name: str) -> None:
    """Remove a tool."""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    tools = data.get("settings", {}).get("tools", {})
    if name not in tools:
        click.echo(f"  Tool '{name}' not found.", err=True)
        sys.exit(1)
    del tools[name]
    _save_raw_config(config_file, data)
    click.echo(f"  Removed tool {S(name, fg='cyan')}")


@config.command("add")
@click.argument("path")
@click.option("--group", "-g", default=None, help="Group name")
@click.option("--tool", "-t", default=None, help="Tool (claude, codex, vscode, ...)")
@click.option("--color", "-c", default=None, help="Tab color (#rrggbb)")
@click.option("--title", default=None, help="Custom window title")
@click.option("--host", default=None, help="SSH host for remote projects")
@click.option("--windows", "-w", default=None, type=int, help="Number of windows")
@click.pass_context
def config_add(
    ctx: click.Context,
    path: str,
    group: str | None,
    tool: str | None,
    color: str | None,
    title: str | None,
    host: str | None,
    windows: int | None,
) -> None:
    """Add a project. Usage: multideck config add ./myapp -g INTERNAL -t claude"""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    data.setdefault("projects", [])

    entry: dict = {"path": path.replace("\\", "/")}
    if group:
        entry["group"] = group
    if tool:
        entry["tool"] = tool
    if color:
        entry["color"] = color
    if title:
        entry["title"] = title
    if host:
        entry["host"] = host
    if windows:
        entry["windows"] = windows

    data["projects"].append(entry)
    _save_raw_config(config_file, data)
    click.echo(f"  Added {S(path, fg='cyan')}")


@config.command("remove")
@click.argument("path")
@click.pass_context
def config_remove(ctx: click.Context, path: str) -> None:
    """Remove a project by path (or leaf name)."""
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    projects = data.get("projects", [])
    normalized = path.replace("\\", "/")

    before = len(projects)
    data["projects"] = [
        p for p in projects
        if p.get("path", "") != normalized and Path(p.get("path", "")).name != path
    ]

    removed = before - len(data["projects"])
    if removed == 0:
        click.echo(f"  No project matching '{path}' found.", err=True)
        sys.exit(1)

    _save_raw_config(config_file, data)
    click.echo(f"  Removed {removed} project(s) matching {S(path, fg='cyan')}")


@config.command("enable")
@click.argument("path")
@click.pass_context
def config_enable(ctx: click.Context, path: str) -> None:
    """Enable a disabled project."""
    _set_project_field(ctx, path, "enabled", True)
    click.echo(f"  Enabled {S(path, fg='cyan')}")


@config.command("disable")
@click.argument("path")
@click.pass_context
def config_disable(ctx: click.Context, path: str) -> None:
    """Disable a project without removing it."""
    _set_project_field(ctx, path, "enabled", False)
    click.echo(f"  Disabled {S(path, fg='cyan')}")


@config.command("set")
@click.argument("path")
@click.argument("field")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, path: str, field: str, value: str) -> None:
    """Set a field on a project. Usage: multideck config set myapp group INTERNAL"""
    parsed: str | int | bool = value
    if value.lower() in ("true", "false"):
        parsed = value.lower() == "true"
    else:
        try:
            parsed = int(value)
        except ValueError:
            pass
    _set_project_field(ctx, path, field, parsed)
    click.echo(f"  Set {S(field, bold=True)} = {S(str(value), fg='cyan')} on {path}")


@config.command("open")
@click.pass_context
def config_open(ctx: click.Context) -> None:
    """Open config file in your default editor."""
    config_file = _find_config(ctx.obj.get("config_path"))
    if not config_file.exists():
        click.echo(f"No config at {config_file}. Run multideck first.", err=True)
        sys.exit(1)
    _open_in_editor(config_file)
    click.echo(f"  Opened {S(str(config_file), dim=True)}")


@config.command("path")
@click.pass_context
def config_path_cmd(ctx: click.Context) -> None:
    """Print the config file path."""
    click.echo(str(_find_config(ctx.obj.get("config_path"))))


def _set_project_field(ctx: click.Context, path: str, field: str, value: object) -> None:
    config_file = _find_config(ctx.obj.get("config_path"))
    data = _load_raw_config(config_file)
    normalized = path.replace("\\", "/")

    found = False
    for p in data.get("projects", []):
        if p.get("path", "") == normalized or Path(p.get("path", "")).name == path:
            p[field] = value
            found = True
            break

    if not found:
        click.echo(f"  No project matching '{path}' found.", err=True)
        sys.exit(1)

    _save_raw_config(config_file, data)
