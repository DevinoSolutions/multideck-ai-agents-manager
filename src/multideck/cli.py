from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from multideck import __version__
from multideck.config import _random_tab_color, load_config
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


def _grid_preview(cols: int, rows: int, indent: str = "  ") -> list[str]:
    cell_w = 10
    lines: list[str] = []
    border = "+" + (f"{'-' * cell_w}+") * cols
    for r in range(rows):
        lines.append(f"{indent}{S(border, dim=True)}")
        cells = ""
        for c in range(cols):
            n = r * cols + c + 1
            label = f"win {n}"
            pad = cell_w - len(label)
            left = pad // 2
            right = pad - left
            cells += S("|", dim=True) + " " * left + S(label, fg="cyan") + " " * right
        cells += S("|", dim=True)
        lines.append(f"{indent}{cells}")
    lines.append(f"{indent}{S(border, dim=True)}")
    return lines


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


def _confirm_change(message: str) -> None:
    click.echo(f"\n  {S('+', fg='green', bold=True)} {message}")
    click.echo(f"  {S('Press Enter to continue...', dim=True)}", nl=False)
    click.getchar()
    click.echo()


def _prompt_or_back(label: str, default: str = "", **kwargs) -> str | None:
    hint = S("  (b to go back)", dim=True)
    value = click.prompt(f"  {label}{hint}", default=default, **kwargs).strip()
    if value.lower() == "b":
        return None
    return value


def _config_menu(config_file: Path) -> None:
    """Interactive config editor accessed from the main menu."""
    while True:
        click.clear()
        _banner()
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
        click.echo(f"  {S('Each screen is tiled like this:', dim=True)}")
        click.echo()
        for line in _grid_preview(cols, rows, indent="      "):
            click.echo(line)
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
        happy_on = settings.get("happy", False)
        happy_label = S("ON", fg="green", bold=True) if happy_on else S("off", dim=True)
        _menu_item("5", f"Happy mobile      {happy_label}"
                   f"  {S('-- monitor sessions from phone/web', dim=True)}")
        psmux_on = settings.get("psmux", False)
        psmux_label = S("ON", fg="green", bold=True) if psmux_on else S("off", dim=True)
        _menu_item("6", f"psmux sessions    {psmux_label}"
                   f"  {S('-- attach from SSH / phone', dim=True)}")
        upload_on = settings.get("uploadServer", False)
        upload_port = settings.get("uploadPort", 8033)
        upload_label = S(f"ON :{upload_port}", fg="green", bold=True) if upload_on else S("off", dim=True)
        _menu_item("7", f"Upload server     {upload_label}"
                   f"  {S('-- send images from phone to Claude', dim=True)}")
        click.echo()
        click.echo(f"  {S('Projects', bold=True)}")
        _divider()
        click.echo()
        _menu_item("8", f"Add a project     {S('-- register a new folder', dim=True)}")
        _menu_item("9", f"Remove a project  {S(f'({len(projects)} configured)', dim=True)}")
        click.echo()
        _menu_item("0", f"Open config file in editor", key_fg="green")
        _menu_item("b", "Back to main menu", key_fg="yellow")
        click.echo()

        choice = click.prompt(f"  {S('>', fg='cyan', bold=True)}", default="b", show_default=False, prompt_suffix=" ").strip().lower()

        if choice == "1":
            click.echo()
            click.echo(f"  {S('How many windows per screen?', bold=True)}")
            click.echo(f"  {S('Columns = side by side, Rows = stacked.', dim=True)}")
            click.echo()
            val = _prompt_or_back("Columns (side by side)", default=str(cols))
            if val is None:
                continue
            try:
                new_cols = max(1, int(val))
            except ValueError:
                continue
            val = _prompt_or_back("Rows (stacked)", default=str(rows))
            if val is None:
                continue
            try:
                new_rows = max(1, int(val))
            except ValueError:
                continue
            click.echo()
            click.echo(f"  {S('Your screens will look like:', bold=True)}")
            click.echo()
            for line in _grid_preview(new_cols, new_rows, indent="      "):
                click.echo(line)
            data.setdefault("layout", {})
            data["layout"]["columns"] = new_cols
            data["layout"]["rows"] = new_rows
            _save_raw_config(config_file, data)
            _confirm_change(f"Window grid set to {S(f'{new_cols} x {new_rows}', fg='green')}"
                            f" ({new_cols * new_rows} windows per screen).")

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
            val = _prompt_or_back("Pick a number or type a name", default=dtool, show_default=False)
            if val is None:
                continue
            try:
                idx = int(val) - 1
                if 0 <= idx < len(available):
                    val = available[idx]
            except ValueError:
                pass
            data.setdefault("settings", {})
            data["settings"]["defaultTool"] = val
            _save_raw_config(config_file, data)
            _confirm_change(f"Default tool set to {S(val, fg='green')}.")

        elif choice == "3":
            click.echo()
            click.echo(f"  {S('Where are your projects?', bold=True)}")
            click.echo(f"  {S('Project paths in your config are relative to this folder.', dim=True)}")
            click.echo(f"  {S('Example: if base is C:/projects and a project path is', dim=True)}")
            click.echo(f"  {S('api/backend, it opens C:/projects/api/backend.', dim=True)}")
            click.echo()
            val = _prompt_or_back("Projects folder", default=data.get("baseDir", ""))
            if val is None or not val:
                continue
            normalized = val.replace("\\", "/")
            data["baseDir"] = normalized
            _save_raw_config(config_file, data)
            _confirm_change(f"Projects folder set to {S(normalized, fg='green')}.")

        elif choice == "4":
            _tools_menu(config_file, data)

        elif choice == "5":
            data.setdefault("settings", {})
            new_val = not data["settings"].get("happy", False)
            data["settings"]["happy"] = new_val
            _save_raw_config(config_file, data)
            if new_val:
                _confirm_change(f"Happy mobile {S('enabled', fg='green')}. "
                                f"Sessions will be accessible from your phone via the Happy app.")
            else:
                _confirm_change(f"Happy mobile {S('disabled', dim=True)}. "
                                f"Sessions launch directly without Happy.")

        elif choice == "6":
            data.setdefault("settings", {})
            new_val = not data["settings"].get("psmux", False)
            data["settings"]["psmux"] = new_val
            _save_raw_config(config_file, data)
            if new_val:
                _confirm_change(f"psmux sessions {S('enabled', fg='green')}. "
                                f"Each project runs in a named psmux session you can attach to via SSH.")
            else:
                _confirm_change(f"psmux sessions {S('disabled', dim=True)}. "
                                f"Projects launch in regular Windows Terminal tabs.")

        elif choice == "7":
            data.setdefault("settings", {})
            currently_on = data["settings"].get("uploadServer", False)
            if currently_on:
                data["settings"]["uploadServer"] = False
                _save_raw_config(config_file, data)
                _confirm_change(f"Upload server {S('disabled', dim=True)}.")
            else:
                click.echo()
                cur_port = data["settings"].get("uploadPort", 8033)
                val = _prompt_or_back(f"Port {S(f'(Enter for {cur_port})', dim=True)}",
                                      default=str(cur_port), show_default=False)
                if val is None:
                    continue
                try:
                    port = int(val)
                except ValueError:
                    continue
                data["settings"]["uploadServer"] = True
                data["settings"]["uploadPort"] = port
                _save_raw_config(config_file, data)
                _confirm_change(f"Upload server {S('enabled', fg='green')} on port {S(str(port), fg='cyan')}. "
                                f"Starts automatically with multideck.")

        elif choice == "8":
            cwd = str(Path.cwd()).replace("\\", "/")
            click.echo()
            click.echo(f"  {S('Add a project folder for multideck to open.', bold=True)}")
            click.echo(f"  {S('Path can be absolute or relative to your projects folder.', dim=True)}")
            click.echo(f"  {S(f'Press Enter to use the current folder.', dim=True)}")
            click.echo()
            path = _prompt_or_back("Folder path", default=cwd)
            if path is None or not path:
                continue
            entry: dict = {"path": path.replace("\\", "/")}
            click.echo()
            click.echo(f"  {S('Optional settings (Enter to skip, b to cancel):', dim=True)}")
            click.echo()
            group = _prompt_or_back(f"Group {S('-- for launching subsets, e.g. INTERNAL', dim=True)}",
                                    default="", show_default=False)
            if group is None:
                continue
            if group:
                entry["group"] = group
            tool = _prompt_or_back(f"Tool  {S('-- override default, e.g. codex, vscode', dim=True)}",
                                   default="", show_default=False)
            if tool is None:
                continue
            if tool:
                entry["tool"] = tool
            color = _prompt_or_back(f"Color {S('-- terminal tab color, Enter for random', dim=True)}",
                                    default="", show_default=False)
            if color is None:
                continue
            if not color:
                used = {p.get("color") for p in data.get("projects", []) if p.get("color")}
                color = _random_tab_color(used)
            entry["color"] = color
            data.setdefault("projects", []).append(entry)
            _save_raw_config(config_file, data)
            _confirm_change(f"Added project {S(path, fg='green')}.")

        elif choice == "9":
            _remove_project_menu(config_file, data)

        elif choice == "0":
            _open_in_editor(config_file)
            return

        elif choice == "b":
            return


def _tools_menu(config_file: Path, data: dict) -> None:
    tools = data.get("settings", {}).get("tools", {})
    while True:
        click.clear()
        _banner()
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
            name = _prompt_or_back("Tool name")
            if not name:
                continue
            existing = tools.get(name, "")
            cmd = _prompt_or_back("Shell command to run", default=existing)
            if cmd is None:
                continue
            data.setdefault("settings", {}).setdefault("tools", {})
            data["settings"]["tools"][name] = cmd
            tools = data["settings"]["tools"]
            _save_raw_config(config_file, data)
            _confirm_change(f"Tool {S(name, fg='green')} set to {S(cmd, dim=True)}.")

        elif choice == "r":
            if not tools:
                click.echo(f"  {S('No tools to remove.', dim=True)}")
                continue
            click.echo()
            tool_names = list(tools.keys())
            for i, name in enumerate(tool_names, 1):
                _menu_item(str(i), name)
            click.echo()
            val = _prompt_or_back("Remove which?")
            if val is None:
                continue
            try:
                idx = int(val) - 1
                if 0 <= idx < len(tool_names):
                    removed_name = tool_names[idx]
                    del tools[removed_name]
                    _save_raw_config(config_file, data)
                    _confirm_change(f"Removed tool {S(removed_name, fg='green')}.")
            except (ValueError, IndexError):
                click.echo(f"  {S('x', fg='red')} Invalid choice.")

        elif choice == "b":
            return


def _remove_project_menu(config_file: Path, data: dict) -> None:
    projects = data.get("projects", [])
    if not projects:
        click.echo(f"  {S('No projects to remove.', dim=True)}")
        return

    click.clear()
    _banner()
    for i, p in enumerate(projects, 1):
        leaf = Path(p.get("path", "?")).name
        extra = ""
        if p.get("group"):
            extra = f"  {S(p['group'], dim=True)}"
        if not p.get("enabled", True):
            extra += f"  {S('disabled', fg='red')}"
        click.echo(f"   {S(str(i).rjust(2), dim=True)}  {leaf:<30}{extra}")

    click.echo()
    val = _prompt_or_back("Remove which?")
    if val is None:
        return
    try:
        idx = int(val) - 1
        if 0 <= idx < len(projects):
            removed = projects.pop(idx)
            _save_raw_config(config_file, data)
            _confirm_change(f"Removed project {S(Path(removed.get('path', '?')).name, fg='green')}.")
        else:
            click.echo(f"  {S('x', fg='red')} Invalid number.")
    except ValueError:
        click.echo(f"  {S('x', fg='red')} Invalid choice.")


def _show_menu(groups: list[str], config_file: Path | None = None) -> dict:
    config_changed = False
    while True:
        click.clear()
        _banner()
        _divider()
        click.echo()
        _menu_item("1", "Launch & tile new windows", extra=S("  (default)", dim=True))
        _menu_item("2", "Re-tile all open windows")
        if groups:
            group_list = S(f"  {' | '.join(groups)}", dim=True)
            _menu_item("3", "Launch a group" + group_list)
        click.echo()
        _menu_item("u", "Bring up sessions in background", key_fg="cyan",
                   extra=S("  (no windows)", dim=True))
        _menu_item("s", "Open session switcher", key_fg="cyan",
                   extra=S("  (one window, switch inside)", dim=True))
        _menu_item("a", "Attach to a remote host", key_fg="cyan",
                   extra=S("  (SSH to another PC)", dim=True))
        click.echo()
        _menu_item("t", "Status", extra=S("  (what's running)", dim=True))
        _menu_item("d", "Shut down sessions", key_fg="yellow")
        click.echo()
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
        elif choice == "u":
            return {"action": "up", "reload": config_changed}
        elif choice == "s":
            return {"action": "sessions", "reload": config_changed}
        elif choice == "a":
            return {"action": "attach", "reload": config_changed}
        elif choice == "t":
            return {"action": "status", "reload": config_changed}
        elif choice == "d":
            return {"action": "down", "reload": config_changed}
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
@click.option("--attach-to", "attach_host", default=None, help="Attach to remote psmux sessions (host or user@host)")
@click.option("--attach-port", default=8033, hidden=True, help="(deprecated) port is now read from the host config")
@click.option("--no-mux", "attach_no_mux", is_flag=True, help="With --attach-to: one plain SSH window per project (no psmux/tmux)")
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
    attach_host: str | None,
    attach_port: int,
    attach_no_mux: bool,
) -> None:
    """Open every project in its own terminal and auto-tile across all monitors."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path

    if ctx.invoked_subcommand is not None:
        return

    if attach_host:
        _attach_flow(attach_host, no_mux=attach_no_mux, group=group)
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
        while True:
            groups = sorted({p.group for p in cfg.projects if p.group})
            menu = _show_menu(list(groups), config_file)
            action = menu["action"]
            if action == "quit":
                return
            if action == "attach":
                _attach_flow(None, no_mux=False)
                return
            if action == "sessions":
                _run_sessions_picker(config_file)
                continue
            if action == "status":
                _menu_status(config_file)
                continue
            if action == "up":
                _menu_up(config_file)
                continue
            if action == "down":
                _menu_down(config_file)
                continue
            if menu.get("reload"):
                cfg = load_config(str(config_file))
            retile_all = menu["retile_all"]
            group = menu.get("group")
            break

    from multideck.launch import run_multideck, RunOpts
    run_multideck(cfg, RunOpts(
        retile_all=retile_all,
        dry_run=dry_run,
        group=group,
        config_path=str(config_file),
    ))


def _default_attach_host() -> str | None:
    """Best-guess SSH target from the local config's project ``host`` fields."""
    from collections import Counter
    try:
        data = json.loads(_find_config(None).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    hosts = [p.get("host") for p in data.get("projects", []) if p.get("host")]
    if not hosts:
        return None
    return Counter(hosts).most_common(1)[0][0]


def _split_target(host: str) -> tuple[str, str]:
    import getpass
    if "@" in host:
        user, hostname = host.split("@", 1)
        return user, hostname
    return getpass.getuser(), host


def _ssh_capture(target: str, remote_cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a single non-interactive SSH command, returning (rc, stdout, stderr)."""
    import subprocess
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, remote_cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "ssh timed out"
    except FileNotFoundError:
        return 127, "", "ssh not found on PATH"


def _ssh_json(target: str, remote_cmd: str, timeout: int = 30) -> dict | None:
    """Run a remote command and parse its last single-line JSON object (skips banners)."""
    _, out, _ = _ssh_capture(target, remote_cmd, timeout)
    for line in reversed([ln.strip() for ln in out.splitlines() if ln.strip()]):
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def _tile_titles(titles: list[str]) -> None:
    """Tile already-opened windows (matched by exact title) into the monitor grid."""
    import time
    from multideck.grid import Rect, compute_grid
    from multideck.platform import get_platform

    plat = get_platform()
    plat.set_dpi_aware()
    monitors = plat.list_monitors()
    if not monitors:
        click.echo(f"  {S('!', fg='yellow')} No monitors detected; windows opened but not tiled.")
        return
    slots = compute_grid(monitors, 2, 1)

    click.echo(f"\n  {S('#', fg='cyan')} Tiling {len(titles)} window(s)...")
    time.sleep(3)
    for i, title in enumerate(titles):
        pos = slots[i % len(slots)]
        handle = plat.find_window(title, mode="exact")
        if handle is None:
            for _ in range(6):
                time.sleep(1)
                handle = plat.find_window(title, mode="exact")
                if handle is not None:
                    break
        if handle is not None:
            plat.move_window(handle, Rect(x=pos.x, y=pos.y, w=pos.w, h=pos.h))
            click.echo(f"    {S('+', fg='green')} {title}")
        else:
            click.echo(f"    {S('x', fg='red')} {title} {S('not found', dim=True)}")


def _grouped(entries: list[dict]) -> tuple[list[str], dict[str, list[str]]]:
    """Bucket session entries by project group, preserving first-seen order."""
    order: list[str] = []
    buckets: dict[str, list[str]] = {}
    for e in entries:
        g = e.get("group") or "(no group)"
        if g not in buckets:
            buckets[g] = []
            order.append(g)
        buckets[g].append(e["name"])
    return order, buckets


def _print_names(names: list[str], indent: str = "       ", width: int = 66) -> None:
    line = indent
    for nm in names:
        if line.strip() and len(line) + len(nm) + 2 > width:
            click.echo(S(line, dim=True))
            line = indent
        line += nm + "  "
    if line.strip():
        click.echo(S(line, dim=True))


def _print_session_overview(hostname: str, up: list[dict], down: list[dict]) -> list[str]:
    """Render a grouped up/down overview; return the ordered list of pickable groups."""
    dn_order, dn_buckets = _grouped(down)
    up_order, up_buckets = _grouped(up)

    click.echo()
    click.echo(f"  {S('Sessions on', bold=True)} {S(hostname, fg='cyan')}    "
               f"{S(str(len(up)), fg='green', bold=True)} up  {S('/', dim=True)}  "
               f"{S(str(len(down)), fg='yellow', bold=True)} down")
    _divider()

    pickable: list[str] = []
    for g in dn_order:
        names = dn_buckets[g]
        up_n = len(up_buckets.get(g, []))
        total = up_n + len(names)
        if g == "(no group)":
            click.echo(f"     {S(g, dim=True)}  {S(f'{up_n}/{total}', dim=True)}")
        else:
            pickable.append(g)
            num = S(str(len(pickable)), fg="cyan", bold=True)
            click.echo(f"  {num}  {S(g, bold=True)}  {S(f'{up_n}/{total} up', dim=True)}")
        _print_names(names)

    for g in up_order:
        if g not in dn_buckets:
            cnt = len(up_buckets[g])
            click.echo(f"     {S(g, dim=True)}  {S(f'{cnt}/{cnt} ready', fg='green')}")
    _divider()
    return pickable


def _bring_up_and_requery(target: str, grp_suffix: str, fallback_up: list[dict]) -> list[dict]:
    import time
    click.echo(f"  {S('o', fg='cyan')} starting sessions on host (this can take a moment)...")
    rc, _, err = _ssh_capture(target, f"multideck up{grp_suffix}", timeout=300)
    if rc != 0:
        click.echo(f"  {S('!', fg='yellow')} bring-up exited {rc}: {S(err.strip()[:200], dim=True)}")
    time.sleep(1)
    new = _ssh_json(target, f"multideck up --json{grp_suffix}", timeout=30)
    return new.get("up", fallback_up) if new else fallback_up


def _attach_flow(host: str | None, no_mux: bool = False, group: str | None = None,
                 yes: bool = False) -> None:
    """Remote-PC attach: bring the host's sessions up, then open local windows.

    Default (psmux): tile one local window per remote psmux session and run the
    Alt+V image hotkey. ``--no-mux``: open one plain SSH window per project that
    runs the agent directly (no multiplexer). ``group`` limits the whole flow to
    one project group on the host; ``yes`` skips the bring-up prompt.
    """
    import subprocess
    import time

    grp = f' -g "{group}"' if group else ""

    if not host:
        default = _default_attach_host()
        host = click.prompt(
            f"  {S('SSH host', fg='cyan')} {S('(user@host -- blank uses config)', dim=True)}",
            default=default or "", show_default=bool(default),
        ).strip()
    if not host:
        click.echo(f"  {S('x', fg='red')} No host provided.")
        sys.exit(1)

    user, hostname = _split_target(host)
    target = f"{user}@{hostname}"

    _banner()
    mode_tag = S("[no-mux]", fg="yellow") if no_mux else S("[psmux]", fg="cyan")
    grp_tag = f"  {S(f'group={group}', fg='cyan')}" if group else ""
    click.echo(f"  {S('Attach', bold=True)}  {S(f'-> {target}', dim=True)}  {mode_tag}{grp_tag}")
    _divider()
    click.echo()

    click.echo(f"  {S('Querying projects on host...', dim=True)}")
    status = _ssh_json(target, f"multideck up --json{grp}", timeout=30)
    if status is None:
        rc, _, _ = _ssh_capture(target, "multideck --version")
        click.echo(f"\n  {S('x', fg='red')} Could not read project status from {target}.")
        if rc != 0:
            click.echo(f"  {S('Is multideck installed and on PATH on the host?', dim=True)}")
        sys.exit(1)
    if status.get("error"):
        click.echo(f"\n  {S('x', fg='red')} Host error: {status['error']}")
        sys.exit(1)
    if not status.get("projects"):
        where = f" in group '{group}'" if group else ""
        click.echo(f"\n  {S('x', fg='red')} No eligible projects{where} on the host.")
        sys.exit(1)

    if no_mux:
        _attach_nomux(target, status)
        return

    up = status.get("up", [])
    down = status.get("down", [])
    port = status.get("uploadPort", 8033)

    if down and yes:
        up = _bring_up_and_requery(target, grp, up)
    elif down:
        pickable = _print_session_overview(hostname, up, down)
        opts = [f"{S('a', fg='cyan', bold=True)}=all {len(down)}"]
        if pickable:
            opts.append(f"{S('1-' + str(len(pickable)), fg='cyan', bold=True)}=one group")
        opts.append(f"{S('n', fg='cyan', bold=True)}=none")
        click.echo(f"  {S('Bring up', bold=True)}   " + "   ".join(opts))
        choice = click.prompt(f"  {S('>', fg='cyan', bold=True)}", default="a",
                              show_default=False, prompt_suffix=" ").strip().lower()

        if choice in ("n", "no", "none", "q"):
            pass
        elif choice in ("a", "y", "all", ""):
            up = _bring_up_and_requery(target, grp, up)
        else:
            sel = None
            if choice.isdigit() and 1 <= int(choice) <= len(pickable):
                sel = pickable[int(choice) - 1]
            else:
                sel = next((g for g in pickable if g.lower() == choice), None)
            if sel:
                up = _bring_up_and_requery(target, f' -g "{sel}"', up)
            else:
                click.echo(f"  {S('?', fg='yellow')} unrecognized choice -- bringing up none.")

    if not up:
        click.echo(f"\n  {S('x', fg='red')} No sessions are up on the host.")
        sys.exit(1)

    titles: list[str] = []
    for sess in up:
        name = sess["name"]
        title = f"md:{name}"
        click.echo(f"  {S('o', fg='cyan')} {title}")
        subprocess.Popen([
            "wt", "-w", "new", "--title", title, "--suppressApplicationTitle",
            "--", "ssh", "-t", target, f"multideck sessions {name}",
        ])
        titles.append(title)
        time.sleep(0.4)

    _tile_titles(titles)

    # Guarantee the host runs an upload server for Alt+V -- independent of the
    # host's uploadServer flag and of whether anything was just brought up.
    rc, _, _ = _ssh_capture(target, f"multideck serve -p {port} --ensure", timeout=15)
    if rc != 0:
        click.echo(f"  {S('!', fg='yellow')} couldn't confirm an upload server on the host"
                   f" {S('-- Alt+V may not work', dim=True)}")

    server_url = f"http://{hostname}:{port}"
    click.echo(f"\n  {S('#', fg='magenta')} Hotkey {S('Alt+V', bold=True)} pastes clipboard images"
               f" {S('(only in md: windows)', dim=True)} {S('->', dim=True)} {S(server_url, fg='cyan')}")
    if sys.platform == "win32":
        pid = _maybe_start_hotkey(server_url)
        if pid:
            click.echo(f"  {S('+', fg='green')} Alt+V listener running in the background "
                       f"{S(f'(pid {pid})', dim=True)}")
            click.echo(f"  {S('Progress shows in each md: window. Stop with', dim=True)} "
                       f"{S('multideck down --all', bold=True)}{S('.', dim=True)}")
        else:
            click.echo(f"  {S('!', fg='yellow')} couldn't start the Alt+V listener")


def _attach_nomux(target: str, status: dict) -> None:
    """Open one plain SSH window per project, running the agent directly (no psmux)."""
    import subprocess
    import time

    projects = status.get("projects", [])
    if not projects:
        click.echo(f"  {S('x', fg='red')} No eligible projects in the host config.")
        sys.exit(1)

    click.echo(f"  {S(str(len(projects)), fg='green', bold=True)} project(s) "
               f"{S('-- direct SSH, no multiplexer', dim=True)}\n")

    titles: list[str] = []
    for p in projects:
        title = f"md:{p['name']}"
        remote_dir = p.get("resolved") or p["path"]
        cmd = p.get("cmd") or "claude --continue"
        click.echo(f"  {S('o', fg='cyan')} {title}")
        subprocess.Popen([
            "wt", "-w", "new", "--title", title, "--suppressApplicationTitle",
            "--", "ssh", "-t", target, f"cd {remote_dir} && {cmd}",
        ])
        titles.append(title)
        time.sleep(0.4)

    _tile_titles(titles)
    click.echo(f"\n  {S('Done.', fg='green', bold=True)} "
               f"{S('(no-mux mode: Alt+V image paste is not available)', dim=True)}")


def _maybe_start_upload_server(port: int, config_path: str | None) -> None:
    """Start the upload server detached, unless something is already on the port."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        probe.connect(("127.0.0.1", port))
        return  # already listening
    except OSError:
        pass
    finally:
        probe.close()

    args = [sys.executable, "-m", "multideck"]
    if config_path:
        args += ["--config", config_path]
    args += ["serve", "-p", str(port)]
    # Must outlive the SSH bring-up command that spawns it -- see spawn_detached.
    from multideck.launch import spawn_detached
    spawn_detached(args)


def _maybe_start_hotkey(server_url: str) -> int | None:
    """Start the Alt+V listener hidden in the background, unless one is running.

    The listener's progress now shows in the md: windows, so it needs no terminal
    of its own -- attach launches it detached and returns, instead of blocking a
    terminal on a message loop. Returns the listener pid (existing or freshly
    started), or None if it couldn't be confirmed.
    """
    if sys.platform != "win32":
        return None
    import time

    from multideck.hotkey import listener_pid

    existing = listener_pid()
    if existing:
        return existing

    args = [sys.executable, "-m", "multideck", "hotkey", "-s", server_url]
    from multideck.launch import spawn_detached
    spawn_detached(args)
    # The child writes its pid only after the keyboard hook installs; give it a
    # short window to come up so we can report (and so a hook failure surfaces).
    for _ in range(20):
        time.sleep(0.1)
        pid = listener_pid()
        if pid:
            return pid
    return None


@main.command("up")
@click.option("--json", "as_json", is_flag=True, help="Print session status as JSON without changing anything")
@click.option("--all", "do_all", is_flag=True, help="Recreate every session, not just the ones that are down")
@click.option("-g", "--group", default=None, help="Only projects tagged with this group")
@click.pass_context
def up_cmd(ctx: click.Context, as_json: bool, do_all: bool, group: str | None) -> None:
    """Ensure a persistent psmux session per project (host side of `attach`)."""
    config_file = _find_config(ctx.obj.get("config_path"))
    try:
        cfg = load_config(str(config_file))
    except (ValueError, FileNotFoundError) as e:
        if as_json:
            click.echo(json.dumps({"error": str(e)}))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    from multideck.launch import bring_up_psmux, psmux_status

    up, down, projects = psmux_status(cfg, group=group)

    if as_json:
        click.echo(json.dumps({
            "platform": sys.platform,
            "psmux": cfg.settings.psmux,
            "uploadServer": cfg.settings.upload_server,
            "uploadPort": cfg.settings.upload_port,
            "up": up,
            "down": down,
            "projects": [
                {"name": p["name"], "path": p["path"], "tool": p["tool"],
                 "group": p["group"], "resolved": p["resolved"], "cmd": p["cmd"]}
                for p in projects
            ],
        }))
        return

    _banner()
    click.echo(f"  {S('Bring up sessions', bold=True)}  {S(str(config_file), dim=True)}")
    _divider()
    click.echo()

    targets = None if do_all else [d["name"] for d in down]
    if not projects:
        where = f" in group '{group}'" if group else ""
        click.echo(f"  {S('!', fg='yellow')} No eligible projects{where}.")
    elif not do_all and not down:
        click.echo(f"  {S('+', fg='green')} All {len(up)} session(s) already up.")
    else:
        created = bring_up_psmux(cfg, only=targets, group=group)
        click.echo(f"  {S('+', fg='green')} Brought up {S(str(len(created)), fg='green', bold=True)}"
                   f" session(s): {S(', '.join(created) or '(none)', dim=True)}")

    if cfg.settings.upload_server:
        _maybe_start_upload_server(cfg.settings.upload_port, str(config_file))
        click.echo(f"  {S('#', fg='magenta')} upload server on port {S(str(cfg.settings.upload_port), fg='cyan')}")


@main.command("attach")
@click.argument("host", required=False)
@click.option("--no-mux", is_flag=True, help="One plain SSH window per project (no psmux/tmux)")
@click.option("-g", "--group", default=None, help="Only attach/bring up projects in this group")
@click.option("-y", "--yes", is_flag=True, help="Skip the bring-up prompt (bring up everything that's down)")
@click.pass_context
def attach_cmd(ctx: click.Context, host: str | None, no_mux: bool, group: str | None, yes: bool) -> None:
    """Attach to another machine's multideck sessions over SSH.

    HOST is user@host (omit to be prompted; blank uses the host from your local
    config). Default tiles one window per remote psmux session with Alt+V image
    paste; --no-mux opens a direct SSH window per project instead. -g limits the
    flow to one project group on the host; -y skips the bring-up prompt.
    """
    _attach_flow(host, no_mux=no_mux, group=group, yes=yes)


@main.command("hotkey")
@click.option("--server", "-s", default="http://localhost:8033", help="Upload server URL")
@click.pass_context
def hotkey_cmd(ctx: click.Context, server: str) -> None:
    """Listen for Alt+V to upload clipboard images to psmux sessions.

    Only activates when a 'md:' titled window is focused. Otherwise
    the keystroke passes through normally.
    """
    if sys.platform != "win32":
        click.echo(f"  {S('x', fg='red')} Hotkey listener is Windows-only.")
        sys.exit(1)

    from multideck.hotkey import listener_pid
    existing = listener_pid()
    if existing:
        click.echo(f"  {S('!', fg='yellow')} An Alt+V listener is already running "
                   f"{S(f'(pid {existing})', dim=True)}.")
        click.echo(f"  {S('Stop it first with', dim=True)} {S('multideck down --all', bold=True)}{S('.', dim=True)}")
        return

    _banner()
    click.echo(f"  {S('Hotkey listener', bold=True)}  {S(f'-> {server}', dim=True)}")
    _divider()
    click.echo()
    click.echo(f"  {S('Alt+V', fg='cyan', bold=True)} uploads clipboard image to the focused project")
    click.echo(f"  {S('Only active in windows titled md:<project>', dim=True)}")
    click.echo(f"  {S('Ctrl+C to stop.', dim=True)}")
    click.echo()

    from multideck.hotkey import run_hotkey
    try:
        run_hotkey(server)
    except KeyboardInterrupt:
        click.echo(f"\n  {S('Stopped.', dim=True)}")
    except RuntimeError as e:
        click.echo(f"  {S('x', fg='red')} {e}")
        sys.exit(1)


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


# ---------------------------------------------------------------------------
# multideck docs
# ---------------------------------------------------------------------------

_PROJECT_FIELD_DOCS: list[tuple[str, str, str, str]] = [
    ("path", "string", "*(required)*", "Absolute, or relative to `baseDir`."),
    ("group", "string", "none", "Tag for group launches (`-g`)."),
    ("tool", "string", "`defaultTool`", "`claude`, `codex`, `cursor-agent`, `agy`, `vscode`, `cursor`, or any custom tool."),
    ("color", "string", "random", "Terminal tab color (`#rrggbb`)."),
    ("title", "string", "folder name", "Window title for matching."),
    ("enabled", "boolean", "`true`", "Set `false` to skip without deleting."),
    ("happy", "boolean", "inherit", "Override global Happy setting for this project."),
    ("host", "string", "none", "SSH target for remote projects."),
    ("remotePath", "string", "`path`", "Remote directory when different from `path`."),
    ("windows", "int or list", "none", "`int` or `[\"name1\", \"name2\"]` for multi-window sessions."),
]

_SETTINGS_FIELD_DOCS: list[tuple[str, str, str, str]] = [
    ("defaultTool", "string", "`\"claude\"`", "AI tool launched in each project unless overridden."),
    ("settleSeconds", "int", "`3`", "Seconds to wait for windows to appear before tiling."),
    ("launchDelayMs", "int", "`400`", "Delay between launching each terminal (ms)."),
    ("happy", "boolean", "`false`", "Enable [Happy](https://github.com/slopus/happy) to access sessions from mobile/web."),
    ("psmux", "boolean", "`false`", "Run CLI agents in psmux sessions (Windows). Attach from SSH with `psmux attach -t <name>`."),
    ("uploadServer", "boolean", "`false`", "Auto-start upload server for mobile image transfer when psmux launches."),
    ("uploadPort", "int", "`8033`", "Port for the upload server."),
    ("tools", "object", "`{\"claude\": ..., \"codex\": ..., \"cursor-agent\": ..., \"agy\": ...}`",
     "Map of tool names to shell commands. Add custom tools here."),
    ("ssh.shell", "string", "`\"bash -lc\"`", "Shell wrapper for remote SSH commands."),
]


def _generate_docs() -> str:
    from multideck.config import LayoutConfig, Settings

    defaults_layout = LayoutConfig()
    defaults_settings = Settings()

    config_locations = {
        "Windows": r"`%APPDATA%\multideck\config.json`",
        "macOS": "`~/Library/Application Support/multideck/config.json`",
        "Linux": "`~/.config/multideck/config.json`",
    }

    lines: list[str] = []
    w = lines.append

    w("# multideck Configuration Reference")
    w("")
    w(f"*Generated from multideck v{__version__} schema.*")
    w("")

    w("## Config file location")
    w("")
    for platform, loc in config_locations.items():
        w(f"- **{platform}:** {loc}")
    w("")
    w("Or place `multideck.config.json` in your working directory (takes priority).")
    w("")

    w("## Top-level fields")
    w("")
    w("| Field | Type | Default | Description |")
    w("| --- | --- | --- | --- |")
    w("| `baseDir` | string | none | Root folder. Project paths are relative to this. |")
    w(f"| `layout.columns` | int | `{defaults_layout.columns}` | Windows side by side per screen. |")
    w(f"| `layout.rows` | int | `{defaults_layout.rows}` | Windows stacked per screen. |")
    w("| `projects` | array | *(required)* | List of project entries (see below). |")
    w("| `settings` | object | see below | Global settings. |")
    w("")

    w("## Settings")
    w("")
    w("All fields under `\"settings\"` in config.json:")
    w("")
    w("| Field | Type | Default | Description |")
    w("| --- | --- | --- | --- |")
    for name, type_, default, desc in _SETTINGS_FIELD_DOCS:
        w(f"| `{name}` | {type_} | {default} | {desc} |")
    w("")

    w("## Project fields")
    w("")
    w("Each entry in the `\"projects\"` array:")
    w("")
    w("| Field | Type | Default | Description |")
    w("| --- | --- | --- | --- |")
    for name, type_, default, desc in _PROJECT_FIELD_DOCS:
        w(f"| `{name}` | {type_} | {default} | {desc} |")
    w("")

    w("## Example config")
    w("")
    w("```json")
    w("{")
    w('  "baseDir": "C:/Users/you/projects",')
    w('  "layout": { "columns": 2, "rows": 1 },')
    w('  "settings": {')
    w(f'    "defaultTool": "{defaults_settings.default_tool}",')
    w(f'    "settleSeconds": {defaults_settings.settle_seconds},')
    w(f'    "launchDelayMs": {defaults_settings.launch_delay_ms},')
    w('    "tools": {')
    for name, cmd in defaults_settings.tools.items():
        w(f'      "{name}": "{cmd}",')
    w('      "aider": "aider --model sonnet"')
    w("    }")
    w("  },")
    w('  "projects": [')
    w('    { "path": "api", "group": "INTERNAL", "color": "#3b82f6" },')
    w('    { "path": "web", "group": "INTERNAL", "tool": "codex" },')
    w('    { "path": "docs", "tool": "vscode" }')
    w("  ]")
    w("}")
    w("```")
    w("")

    w("## Multi-window sessions")
    w("")
    w("Open the same project in multiple windows, each resuming a different conversation:")
    w("")
    w("```json")
    w('{ "path": "api", "windows": 3 }')
    w("```")
    w("")
    w("Opens 3 windows (`api`, `api-2`, `api-3`), each resuming the Nth most recent session.")
    w("")

    w("## Remote projects (SSH)")
    w("")
    w("```json")
    w('{ "host": "deploy@server", "path": "/srv/api", "tool": "claude" }')
    w("```")
    w("")
    w("CLI agents run over SSH. VS Code projects open via Remote-SSH.")
    w("")

    w("## Happy (mobile/web access)")
    w("")
    w("Enable [Happy](https://github.com/slopus/happy) to monitor and control your AI sessions")
    w("from your phone or any browser. Happy wraps supported agents (claude, codex) and relays")
    w("encrypted session data to the Happy mobile/web app.")
    w("")
    w("```json")
    w('"settings": {')
    w('  "happy": true')
    w("}")
    w("```")
    w("")
    w("Requires `npm install -g happy`. Per-project override:")
    w("")
    w("```json")
    w('{ "path": "api", "happy": true }')
    w('{ "path": "docs", "tool": "vscode", "happy": false }')
    w("```")
    w("")

    w("## Custom tools")
    w("")
    w("Add any command under `settings.tools`:")
    w("")
    w("```json")
    w('"tools": {')
    w('  "claude": "claude --continue",')
    w('  "codex": "codex",')
    w('  "cursor-agent": "cursor-agent",')
    w('  "agy": "agy",')
    w('  "aider": "aider --model sonnet",')
    w('  "shell": "bash"')
    w("}")
    w("```")
    w("")
    w("Then use `\"tool\": \"aider\"` on any project, or set it as `defaultTool`.")
    w("")

    w("## CLI commands")
    w("")
    w("| Command | Description |")
    w("| --- | --- |")
    w("| `multideck` | Interactive menu. |")
    w("| `multideck --go` | Launch + tile, skip menu. |")
    w("| `multideck --retile-all` | Re-tile every matching window. |")
    w("| `multideck -g <name>` | Launch only projects in a group. |")
    w("| `multideck --init` | Re-scan sessions and regenerate config. |")
    w("| `multideck --init --base-dir <dir>` | Generate config from a folder of repos. |")
    w("| `multideck --edit` | Open config in your default editor. |")
    w("| `multideck docs` | Print this reference (pipe to file for AI context). |")
    w("| `multideck up` | (Host side) ensure a persistent psmux session per project. |")
    w("| `multideck up --json` | Print session status (up/down/projects) as JSON, change nothing. |")
    w("| `multideck up -g <group>` | Bring up sessions for only one project group. |")
    w("| `multideck attach [host]` | From another PC: bring host sessions up over SSH, tile locally, Alt+V hotkey. |")
    w("| `multideck attach <host> -g <group>` | Attach to only one project group on the host. |")
    w("| `multideck attach <host> --no-mux` | Attach with a direct SSH window per project (no psmux/tmux). |")
    w("| `multideck --attach-to <host>` | (deprecated alias for `multideck attach <host>`). |")
    w("| `multideck status` | Show which psmux sessions and the upload server are running. |")
    w("| `multideck down` | Shut down all running psmux sessions. |")
    w("| `multideck down -g <group>` | Shut down only one group's sessions. |")
    w("| `multideck down <name> [<name>...]` | Shut down specific sessions by name. |")
    w("| `multideck down --all` | Stop every session and the upload server. |")
    w("| `multideck serve` | Start upload server for mobile image transfer. |")
    w("| `multideck serve -p 9090` | Use a custom port (default 8033). |")
    w("| `multideck hotkey` | Listen for Alt+V to upload clipboard images (standalone). |")
    w("| `multideck sessions` | List active psmux sessions, pick one to attach. |")
    w("| `multideck sessions <name>` | Attach directly to a psmux session by name. |")
    w("| `multideck config show` | Display current config. |")
    w("| `multideck config layout <cols> <rows>` | Set window grid. |")
    w("| `multideck config base-dir <path>` | Set projects folder. |")
    w("| `multideck config default-tool <tool>` | Set default AI tool. |")
    w("| `multideck config tool <name> <cmd>` | Add/update a tool command. |")
    w("| `multideck config remove-tool <name>` | Remove a tool. |")
    w("| `multideck config add <path> [-g GROUP] [-t TOOL]` | Add a project. |")
    w("| `multideck config remove <path>` | Remove a project. |")
    w("| `multideck config enable <path>` | Enable a project. |")
    w("| `multideck config disable <path>` | Disable a project. |")
    w("| `multideck config set <path> <field> <value>` | Set a project field. |")
    w("| `multideck config open` | Open config in editor. |")
    w("| `multideck config path` | Print config file path. |")
    w("")

    return "\n".join(lines)


@main.command("docs")
def docs_cmd() -> None:
    """Print the full configuration reference (Markdown). Pipe to a file or feed to an AI."""
    click.echo(_generate_docs())


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
    import shutil
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
@click.option("--ensure", is_flag=True,
              help="Start the server detached if it isn't already running, then exit (used by attach).")
@click.pass_context
def serve_cmd(ctx: click.Context, port: int, ensure: bool) -> None:
    """Start upload server for mobile image transfer.

    Opens a web page on your phone (via Tailscale) where you pick a project,
    upload an image, and the file path is auto-pasted into that project's
    Claude session via psmux send-keys.
    """
    import subprocess

    config_path = ctx.obj.get("config_path")
    if ensure:
        # Non-blocking: ensure a survivor server exists on this port, then return.
        # attach calls this over SSH so the host always has a server for Alt+V,
        # regardless of the uploadServer config flag or whether anything was
        # just brought up.
        _maybe_start_upload_server(port, config_path)
        click.echo(f"upload server ensured on port {port}")
        return

    ip = "0.0.0.0"
    try:
        result = subprocess.run(["tailscale", "ip", "-4"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            ip = result.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    _banner()
    click.echo(f"  {S('Upload server', bold=True)}  {S('for mobile image transfer', dim=True)}")
    _divider()
    click.echo()
    if ip != "0.0.0.0":
        click.echo(f"  {S('Open on phone:', bold=True)}  {S(f'http://{ip}:{port}', fg='cyan', bold=True)}")
    click.echo(f"  {S('Local:', dim=True)}         {S(f'http://localhost:{port}', fg='cyan')}")
    click.echo()
    click.echo(f"  {S('Pick a project, upload a file, path gets pasted into Claude.', dim=True)}")
    click.echo(f"  {S('Ctrl+C to stop.', dim=True)}")
    click.echo()

    from multideck.upload_server import run_server
    try:
        run_server(port=port, config_path=config_path)
    except KeyboardInterrupt:
        click.echo(f"\n  {S('Server stopped.', dim=True)}")


def _force_utf8_console() -> None:
    """Make stdout render UTF-8 (block chars for the QR, box glyphs) on Windows
    consoles that default to a legacy code page. Best-effort, never raises."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _tailnet_host() -> str:
    """Best host for the phone URL: Tailscale MagicDNS name, then its IP, then
    the LAN IP. MagicDNS gives the prettiest, most stable URL."""
    import socket
    import subprocess

    try:
        r = subprocess.run(["tailscale", "status", "--json"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            dns = (json.loads(r.stdout).get("Self") or {}).get("DNSName", "")
            if dns:
                return dns.rstrip(".")
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    try:
        r = subprocess.run(["tailscale", "ip", "-4"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "localhost"


def _pid_alive(pid: int | None) -> bool:
    """Portable best-effort liveness check for a pid."""
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _running_upload_port() -> int | None:
    """Port of a *live* locally-running upload server, from its pid file. Skips
    stale pid files (a port whose recorded process is gone)."""
    import re
    from multideck.upload_server import server_pid
    d = Path.home() / ".multideck"
    if not d.exists():
        return None
    ports = []
    for f in d.glob("upload_server-*.pid"):
        m = re.match(r"upload_server-(\d+)\.pid", f.name)
        if m:
            ports.append(int(m.group(1)))
    alive = [p for p in ports if _pid_alive(server_pid(p))]
    return min(alive) if alive else None


def _print_qr(url: str) -> None:
    """Print a scannable QR for the URL if the qrcode lib is available."""
    try:
        import qrcode
    except ImportError:
        click.echo(f"  {S('Tip:', dim=True)} {S('pip install qrcode', bold=True)} "
                   f"{S('to print a scannable QR code here.', dim=True)}")
        return
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


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
    }.get(state, "")


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
    config_file = _find_config(ctx.obj.get("config_path"))
    _run_sessions_picker(config_file, name)


# ---------------------------------------------------------------------------
# multideck status / down  (inspect and shut down running sessions/services)
# ---------------------------------------------------------------------------

def _probe_port(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _render_status(config_file: Path) -> None:
    from multideck.launch import psmux_status

    cfg = load_config(str(config_file))
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
    on = _probe_port(cfg.settings.upload_port)
    server = (S(f"ON  port {cfg.settings.upload_port}", fg="green", bold=True)
              if on else S("off", dim=True))
    click.echo(f"  {S('Upload server', bold=True)}   {server}")

    pid = None
    if sys.platform == "win32":
        from multideck.hotkey import listener_pid
        pid = listener_pid()
    listener = (S(f"ON  pid {pid}", fg="green", bold=True) if pid
                else S("off  (starts with `multideck attach`)", dim=True))
    click.echo(f"  {S('Alt+V listener', bold=True)}   {listener}")


@main.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show which psmux sessions and services are currently running."""
    config_file = _find_config(ctx.obj.get("config_path"))
    if not config_file.exists():
        click.echo("No config found. Run multideck first.", err=True)
        sys.exit(1)
    _render_status(config_file)


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
    config_file = _find_config(ctx.obj.get("config_path"))
    try:
        cfg = load_config(str(config_file))
    except (ValueError, FileNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

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
            click.echo(f"  {S('-', dim=True)} Upload server was not running.")

    if do_all and sys.platform == "win32":
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

    cfg = load_config(str(config_file))
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

    cfg = load_config(str(config_file))
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
