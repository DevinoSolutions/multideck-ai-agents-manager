<h1 align="center">multideck</h1>

<p align="center">
  <strong>Open every project in its own terminal, launch your AI agent, and auto-tile all windows across your screens.</strong><br />
  One command. Every tool. Every monitor.
</p>

<p align="center">
  <a href="https://pypi.org/project/multideck"><img src="https://img.shields.io/pypi/v/multideck?color=3776AB&label=pypi" alt="PyPI version" /></a>
  <a href="https://pypi.org/project/multideck"><img src="https://img.shields.io/pypi/dm/multideck?color=blue" alt="PyPI downloads" /></a>
  <a href="https://github.com/DevinoSolutions/multideck-ai-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License: AGPL-3.0" /></a>
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+" /></a>
  <img src="https://img.shields.io/badge/dependencies-click-success" alt="Minimal Dependencies" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Windows" />
  <img src="https://img.shields.io/badge/macOS-000000?style=flat-square&logo=apple&logoColor=white" alt="macOS" />
  <img src="https://img.shields.io/badge/Linux-FCC624?style=flat-square&logo=linux&logoColor=black" alt="Linux" />
</p>

---

```
      Monitor 1  (4K @ 250%)         Monitor 2  (4K @ 250%)        Monitor 3 (1080p @ 175%)
   +------------+------------+    +------------+------------+    +---------+---------+
   |   api      |   web      |    |   infra    |   docs     |    |  ops    |   ...   |
   |  [claude]  |  [claude]  |    |  [codex]   |  [vscode]  |    | [claude]|         |
   +------------+------------+    +------------+------------+    +---------+---------+
                     columns x rows per screen -- true physical pixels on every monitor
```

## Quick Start

```bash
pip install multideck
multideck
```

On first run, multideck scans your Claude, Codex, and VS Code history, finds your recent projects, and generates a config. Run it again to launch everything.

## Supported Tools

<table>
  <tr>
    <th>Tool</th>
    <th>Type</th>
    <th>Launch command</th>
    <th>Session resume</th>
    <th>Multi-window</th>
  </tr>
  <tr>
    <td><strong>Claude Code</strong></td>
    <td>CLI agent</td>
    <td><code>claude --continue</code></td>
    <td align="center">Yes</td>
    <td align="center">Yes</td>
  </tr>
  <tr>
    <td><strong>Codex CLI</strong></td>
    <td>CLI agent</td>
    <td><code>codex</code></td>
    <td align="center">Yes</td>
    <td align="center">Yes</td>
  </tr>
  <tr>
    <td><strong>Cursor Agent</strong></td>
    <td>CLI agent</td>
    <td><code>cursor-agent</code></td>
    <td align="center">--</td>
    <td align="center">--</td>
  </tr>
  <tr>
    <td><strong>Antigravity (agy)</strong></td>
    <td>CLI agent</td>
    <td><code>agy</code></td>
    <td align="center">--</td>
    <td align="center">--</td>
  </tr>
  <tr>
    <td><strong>VS Code</strong></td>
    <td>IDE</td>
    <td><code>code</code></td>
    <td align="center">--</td>
    <td align="center">--</td>
  </tr>
  <tr>
    <td><strong>Cursor IDE</strong></td>
    <td>IDE</td>
    <td><code>cursor</code></td>
    <td align="center">--</td>
    <td align="center">--</td>
  </tr>
  <tr>
    <td><strong>Custom</strong></td>
    <td>Any</td>
    <td><em>your command</em></td>
    <td align="center">--</td>
    <td align="center">--</td>
  </tr>
</table>

Add any tool by mapping a name to a shell command in `settings.tools`. CLI agents open in a terminal; IDE tools open via their native CLI (`code`, `cursor`).

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
| `multideck docs` | Print full config reference (Markdown). |

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
      "codex": "codex",
      "cursor-agent": "cursor-agent",
      "agy": "agy",
      "aider": "aider --model sonnet"
    }
  },
  "projects": [
    { "path": "INTERNAL/api",  "group": "INTERNAL", "color": "#3b82f6" },
    { "path": "INTERNAL/web",  "group": "INTERNAL", "color": "#22c55e" },
    { "path": "LEAD-GEN/outreach", "group": "LEAD-GEN", "tool": "codex" },
    { "path": "docs", "tool": "vscode" },
    { "path": "frontend", "tool": "cursor" }
  ]
}
```

### Project fields

| Field | Default | Description |
| --- | --- | --- |
| `path` | *(required)* | Absolute, or relative to `baseDir`. |
| `group` | none | Tag for group launches (`-g`). |
| `tool` | `defaultTool` | `claude`, `codex`, `cursor-agent`, `agy`, `vscode`, `cursor`, or any custom tool. |
| `color` | random | Terminal tab color (`#rrggbb`). |
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

CLI agents run over SSH. VS Code/Cursor projects open via Remote-SSH.

### Custom tools

```json
"tools": {
  "claude": "claude --continue",
  "codex": "codex",
  "cursor-agent": "cursor-agent",
  "agy": "agy",
  "aider": "aider --model sonnet",
  "shell": "bash"
}
```

## Testing

<table>
  <thead>
    <tr>
      <th>Job</th>
      <th align="center" width="180">Live status</th>
      <th>Platforms</th>
      <th>What it verifies</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Unit</strong></td>
      <td align="center"><a href="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml"><img src="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a></td>
      <td>Windows / macOS / Linux<br/>Python 3.10 -- 3.13</td>
      <td>Config parsing, grid computation, title generation, session resume, discovery, grouping (12 matrix jobs)</td>
    </tr>
    <tr>
      <td><strong>Platform</strong></td>
      <td align="center"><a href="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml"><img src="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a></td>
      <td>Windows / macOS / Linux</td>
      <td>Real monitor detection (ctypes/Swift/xrandr), real window find+move, real terminal launch, DPI scaling</td>
    </tr>
    <tr>
      <td><strong>E2E</strong></td>
      <td align="center"><a href="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml"><img src="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a></td>
      <td>Windows / macOS / Linux</td>
      <td>Full CLI dry-run, config loading, group filtering, SSH project handling, vscode/cursor tool alias, multi-window</td>
    </tr>
    <tr>
      <td><strong>Packaging</strong></td>
      <td align="center"><a href="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml"><img src="https://github.com/DevinoSolutions/multideck-ai-agent/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" /></a></td>
      <td>Linux</td>
      <td>Build wheel, install from wheel, <code>multideck --help</code> and <code>--version</code> smoke test</td>
    </tr>
  </tbody>
</table>

### Run it yourself

```bash
pip install -e ".[dev]"
pytest                    # all tests
pytest tests/unit/ -v     # unit tests only
pytest tests/e2e/ -v      # end-to-end tests
pytest tests/platform/ -v # platform-specific tests (needs display)
```

## Cross-platform support

| Feature | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Monitor detection | ctypes Win32 | Swift/AppKit | xrandr |
| Window management | EnumWindows/MoveWindow | AppleScript | xdotool/wmctrl |
| Terminal | Windows Terminal | kitty/iTerm/Terminal.app | kitty/alacritty/gnome-terminal |
| DPI awareness | Per-Monitor V2 | Native Retina | xrandr DPI |

## Install from source

```bash
git clone https://github.com/DevinoSolutions/multideck-ai-agent.git
cd multideck-ai-agent
pip install -e .
```

## Contributing

Contributions are welcome. Please open an issue first to discuss what you'd like to change.

## License

[AGPL-3.0](LICENSE) -- Copyright (c) 2026 [DevinoSolutions](https://github.com/DevinoSolutions)
