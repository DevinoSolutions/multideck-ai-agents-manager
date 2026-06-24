# multideck

**Open every project in its own terminal, launch your AI agent, and auto-tile all windows across your screens. One command.**

![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-blue)
![python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-green)

```
      Monitor 1  (4K @ 250%)         Monitor 2  (4K @ 250%)        Monitor 3 (1080p @ 175%)
   +------------+------------+    +------------+------------+    +---------+---------+
   |   api      |   web      |    |   infra    |   docs     |    |  ops    |   ...   |
   |  [claude]  |  [claude]  |    |  [codex]   |  [vscode]  |    | [claude]|         |
   +------------+------------+    +------------+------------+    +---------+---------+
                     columns x rows per screen -- true physical pixels on every monitor
```

---

## Install

```bash
pip install multideck
```

Or from source:

```bash
git clone https://github.com/DevinoSolutions/multideck-ai-agent.git
cd multideck-ai-agent
pip install -e .
```

## Quick start

Just run it:

```bash
multideck
```

On first run, multideck scans your Claude, Codex, and VS Code history, finds your recent projects, and generates a config. Run it again to launch everything.

## Usage

Run `multideck` with no arguments for the interactive menu:

```
           _ _   _    _        _
 _ __ _  _| | |_(_)__| |___ __| |__
| '  \ || | |  _| / _` / -_) _| / /
|_|_|_\_,_|_|\__|_\__,_\___\__|_\_\
  v1.0.0  auto-tile your AI workspace

  ----------------------------------------

   1   Launch & tile new windows  (default)
   2   Re-tile all open windows
   3   Launch a group  AUTOMATIONS | INTERNAL | LEAD-GEN
   e   Edit config
   q   Quit
```

Or skip the menu with flags:

| Command | What it does |
| --- | --- |
| `multideck` | Interactive menu. |
| `multideck --go` | Launch + tile new windows, no menu. |
| `multideck --retile-all` | Re-tile every matching window. |
| `multideck -g <name>` | Launch only projects in a group. |
| `multideck --init` | Re-scan sessions and regenerate config. |
| `multideck --init --base-dir <folder>` | Generate config from a folder of git repos. |
| `multideck --edit` | Open config in your default editor. |

## Configuration

Config is stored at a platform-standard location:

- **Windows:** `%APPDATA%\multideck\config.json`
- **macOS:** `~/Library/Application Support/multideck/config.json`
- **Linux:** `~/.config/multideck/config.json`

Or place `multideck.config.json` in your working directory.

```json
{
  "baseDir": "C:/Users/you/projects",
  "layout": { "columns": 2, "rows": 1 },
  "settings": {
    "defaultTool": "claude",
    "settleSeconds": 3,
    "launchDelayMs": 400,
    "tools": {
      "claude": "claude --continue",
      "codex": "codex"
    }
  },
  "projects": [
    { "path": "INTERNAL/api",  "group": "INTERNAL", "color": "#3b82f6" },
    { "path": "INTERNAL/web",  "group": "INTERNAL", "color": "#22c55e" },
    { "path": "LEAD-GEN/outreach", "group": "LEAD-GEN", "tool": "codex" },
    { "path": "docs", "tool": "vscode" }
  ]
}
```

### Project fields

| Field | Default | Description |
| --- | --- | --- |
| `path` | *(required)* | Absolute, or relative to `baseDir`. |
| `group` | none | Tag for group launches (`-g`). |
| `tool` | `defaultTool` | `claude`, `codex`, `vscode`/`code`, or any custom tool. |
| `color` | none | Terminal tab color (`#rrggbb`). |
| `title` | folder name | Window title for matching. |
| `enabled` | `true` | Set `false` to skip without deleting. |
| `host` | none | SSH target for remote projects. |
| `remotePath` | `path` | Remote directory when different from `path`. |
| `windows` | none | `int` or `["name1", "name2"]` for multi-window sessions. |

### Multi-window sessions

Open the same project in multiple windows, each resuming a different conversation:

```json
{ "path": "api", "windows": 3 }
```

This opens 3 windows (`api`, `api-2`, `api-3`), each resuming the Nth most recent Claude/Codex session.

### Remote projects

```json
{ "host": "deploy@server", "path": "/srv/api", "tool": "claude" }
```

CLI agents run over SSH. VS Code projects open via Remote-SSH.

### Custom tools

```json
"tools": {
  "claude": "claude --continue",
  "codex": "codex",
  "aider": "aider --model sonnet",
  "shell": "bash"
}
```

## Cross-platform support

| Feature | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Monitor detection | ctypes Win32 | Swift/AppKit | xrandr |
| Window management | EnumWindows/MoveWindow | AppleScript | xdotool/wmctrl |
| Terminal | Windows Terminal | kitty/iTerm/Terminal.app | kitty/alacritty/gnome-terminal |
| DPI awareness | Per-Monitor V2 | Native Retina | xrandr DPI |

## License

MIT
