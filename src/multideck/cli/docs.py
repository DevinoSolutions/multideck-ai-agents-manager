"""The `multideck docs` command: a 190-line pure-string Markdown generator
for the full config reference. No I/O beyond stdout via click.echo.
"""

from __future__ import annotations

import click

from multideck import __version__
from multideck.cli.app import main
from multideck.config import LayoutConfig, Settings

_PROJECT_FIELD_DOCS: list[tuple[str, str, str, str]] = [
    ("path", "string", "*(required)*", "Absolute, or relative to `baseDir`."),
    ("group", "string", "none", "Tag for group launches (`-g`)."),
    (
        "tool",
        "string",
        "`defaultTool`",
        "`claude`, `codex`, `cursor-agent`, `agy`, `vscode`, `cursor`, or any custom tool.",
    ),
    ("color", "string", "derived", "Terminal tab color (`#rrggbb`)."),
    ("title", "string", "folder name", "Window title for matching."),
    ("enabled", "boolean", "`true`", "Set `false` to skip without deleting."),
    ("happy", "boolean", "inherit", "Override global Happy setting for this project."),
    ("host", "string", "none", "SSH target for remote projects."),
    ("remotePath", "string", "`path`", "Remote directory when different from `path`."),
    (
        "windows",
        "list",
        "none",
        'List of window objects `{"name", "tool", "command"}` with per-window tool/command overrides. Legacy `int` / `["name1", "name2"]` forms still parse (normalized by `multideck config migrate`).',
    ),
]


_SETTINGS_FIELD_DOCS: list[tuple[str, str, str, str]] = [
    (
        "defaultTool",
        "string",
        '`"claude"`',
        "AI tool launched in each project unless overridden.",
    ),
    (
        "settleSeconds",
        "int",
        "`3`",
        "Seconds to wait for windows to appear before tiling.",
    ),
    ("launchDelayMs", "int", "`400`", "Delay between launching each terminal (ms)."),
    (
        "happy",
        "boolean",
        "`false`",
        "Enable [Happy](https://github.com/slopus/happy) to access sessions from mobile/web.",
    ),
    (
        "psmux",
        "boolean",
        "`false`",
        "Run CLI agents in psmux sessions (Windows). Attach from SSH with `psmux attach -t <name>`.",
    ),
    (
        "uploadServer",
        "boolean",
        "`false`",
        "Auto-start upload server for mobile image transfer when psmux launches.",
    ),
    ("uploadPort", "int", "`8033`", "Port for the upload server."),
    (
        "tools",
        "object",
        '`{"claude": ..., "codex": ..., "cursor-agent": ..., "agy": ...}`',
        "Map of tool names to shell commands. Add custom tools here.",
    ),
    ("ssh.shell", "string", '`"bash -lc"`', "Shell wrapper for remote SSH commands."),
    (
        "attention.badge",
        "boolean",
        "`true`",
        "Attention daemon rewrites window titles with a state badge (`md:[!] name`).",
    ),
    (
        "attention.flash",
        "boolean",
        "`true`",
        "Flash the taskbar button when a session needs input or errors.",
    ),
    (
        "attention.toast",
        "boolean",
        "`false`",
        "Windows toast on needs-input/error (requires the optional `winotify` extra).",
    ),
    (
        "attention.ntfy",
        "boolean",
        "`false`",
        "Push needs-input/error to an ntfy topic (set `MULTIDECK_NTFY_TOPIC`).",
    ),
    (
        "attention.notifyOnDone",
        "boolean",
        "`false`",
        "Also push toast/ntfy when an agent finishes (enters `done`). Opt-in; "
        "does nothing unless `toast` or `ntfy` is on.",
    ),
]


def _generate_docs() -> str:
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
    w(
        "| `baseDir` | string | none | Root folder. Project paths are relative to this. |"
    )
    w(
        f"| `layout.columns` | int | `{defaults_layout.columns}` | Windows side by side per screen. |"
    )
    w(
        f"| `layout.rows` | int | `{defaults_layout.rows}` | Windows stacked per screen. |"
    )
    w("| `projects` | array | *(required)* | List of project entries (see below). |")
    w("| `settings` | object | see below | Global settings. |")
    w("")

    w("## Settings")
    w("")
    w('All fields under `"settings"` in config.json:')
    w("")
    w("| Field | Type | Default | Description |")
    w("| --- | --- | --- | --- |")
    for name, type_, default, desc in _SETTINGS_FIELD_DOCS:
        w(f"| `{name}` | {type_} | {default} | {desc} |")
    w("")

    w("## Project fields")
    w("")
    w('Each entry in the `"projects"` array:')
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
    # Derive the tools block straight from the factory defaults so the example
    # can never drift from DEFAULT_TOOLS (NF-S3-003 -- no fabricated tools).
    w('    "tools": {')
    tool_items = list(defaults_settings.tools.items())
    for i, (name, cmd) in enumerate(tool_items):
        trailing = "," if i < len(tool_items) - 1 else ""
        w(f'      "{name}": "{cmd}"{trailing}')
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
    w(
        "Open the same project in multiple windows. `windows` is a list of window "
        "objects, each with optional per-window `tool`/`command` overrides:"
    )
    w("")
    w("```json")
    w("{")
    w('  "path": "api",')
    w('  "windows": [')
    w('    { "name": "api" },')
    w('    { "name": "api-2" },')
    w('    { "name": "api-codex", "tool": "codex" }')
    w("  ]")
    w("}")
    w("```")
    w("")
    w(
        "`name` sets the window title; `tool`/`command` override the project's "
        "defaults for that window only. Windows without an override each resume "
        "the Nth most recent session for the project's tool."
    )
    w("")
    w(
        'The legacy `"windows": 3` and `"windows": ["api", "api-2"]` forms still '
        "parse and are normalized to window objects by `multideck config migrate`."
    )
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
    w(
        "Enable [Happy](https://github.com/slopus/happy) to monitor and control your AI sessions"
    )
    w(
        "from your phone or any browser. Happy wraps supported agents (claude, codex) and relays"
    )
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
    w('Then use `"tool": "aider"` on any project, or set it as `defaultTool`.')
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
    w(
        "| `multideck --init --base-dir <dir>` | Generate config from a folder of repos. |"
    )
    w("| `multideck --edit` | Open config in your default editor. |")
    w("| `multideck docs` | Print this reference (pipe to file for AI context). |")
    w("| `multideck up` | (Host side) ensure a persistent psmux session per project. |")
    w(
        "| `multideck up --json` | Print session status (up/down/projects) as JSON, change nothing. |"
    )
    w("| `multideck up -g <group>` | Bring up sessions for only one project group. |")
    w(
        "| `multideck attach [host]` | From another PC: bring host sessions up over SSH, tile locally, Alt+V hotkey. |"
    )
    w(
        "| `multideck attach <host> -g <group>` | Attach to only one project group on the host. |"
    )
    w(
        "| `multideck attach <host> --no-mux` | Attach with a direct SSH window per project (no psmux/tmux). |"
    )
    w(
        "| `multideck --attach-to <host>` | (deprecated alias for `multideck attach <host>`). |"
    )
    w(
        "| `multideck status` | Show which psmux sessions and the upload server are running. |"
    )
    w("| `multideck down` | Shut down all running psmux sessions. |")
    w("| `multideck down -g <group>` | Shut down only one group's sessions. |")
    w("| `multideck down <name> [<name>...]` | Shut down specific sessions by name. |")
    w("| `multideck down --all` | Stop every session and the upload server. |")
    w("| `multideck serve` | Start upload server for mobile image transfer. |")
    w("| `multideck serve -p 9090` | Use a custom port (default 8033). |")
    w(
        "| `multideck hotkey` | Listen for Alt+V to upload clipboard images (standalone). |"
    )
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
    w(
        "| `multideck config migrate` | Stamp the schema version and backfill project colors. |"
    )
    w("")

    return "\n".join(lines)


@main.command("docs")
def docs_cmd() -> None:
    """Print the full configuration reference (Markdown). Pipe to a file or feed to an AI."""
    click.echo(_generate_docs())
