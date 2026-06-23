# Multideck Python Rewrite + Multi-Window Session Resume

**Date:** 2026-06-23
**Status:** Approved
**Scope:** Full rewrite from PowerShell to Python, add multi-window session resume, cross-platform support (Windows/macOS/Linux), PyPI publishing, comprehensive CI/CD.

---

## 1. Overview

Rewrite multideck as a Python CLI tool published on PyPI. Port all existing functionality (config-driven terminal launching, per-monitor DPI-aware tiling, SSH/remote support) and add a new `windows` config field that opens the same project in multiple named windows, each resuming a different conversation by recency.

## 2. Project Structure

```
multideck/
├── src/
│   └── multideck/
│       ├── __init__.py
│       ├── __main__.py             # python -m multideck entry point
│       ├── cli.py                  # click-based CLI
│       ├── config.py               # Config loading, validation, defaults
│       ├── launch.py               # Orchestrator — discover sessions, launch, tile
│       ├── grid.py                 # Grid computation — monitors × rows × cols → tile slots
│       ├── terminals.py            # Terminal emulator detection + adapter registry
│       ├── init_config.py          # Folder scanning + config generation (--init)
│       ├── sessions/
│       │   ├── __init__.py         # Session discovery dispatcher (by tool name)
│       │   ├── claude.py           # Claude session discovery
│       │   └── codex.py            # Codex session discovery
│       └── platform/
│           ├── __init__.py         # Platform detection + abstract interface
│           ├── windows.py          # Win32 via ctypes (built-in)
│           ├── macos.py            # CoreGraphics + AppleScript via subprocess
│           └── linux.py            # xrandr + xdotool/wmctrl via subprocess
├── tests/
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_grid.py
│   │   ├── test_sessions.py
│   │   ├── test_titles.py
│   │   └── test_commands.py
│   ├── platform/
│   │   ├── test_monitors.py
│   │   ├── test_windows.py
│   │   └── test_terminals.py
│   ├── e2e/
│   │   ├── test_launch.py
│   │   ├── test_multi_window.py
│   │   ├── test_ssh.py
│   │   ├── test_idempotency.py
│   │   └── test_cli_flags.py
│   ├── fixtures/
│   │   ├── claude_sessions/        # Fake .jsonl files with controlled mtimes
│   │   └── codex_sessions/         # Fake .jsonl files with CWD metadata
│   ├── conftest.py                 # Shared pytest fixtures
│   └── helpers/
│       ├── virtual_display.py      # Setup/teardown virtual monitors in CI
│       ├── ssh_server.py           # Setup/teardown local SSH server
│       └── poll.py                 # Retry-with-timeout for async window discovery
├── .github/
│   ├── workflows/
│   │   └── ci.yml                  # Matrix: windows/macos/ubuntu × unit/platform/e2e
│   └── actions/
│       ├── setup-virtual-displays/
│       ├── setup-ssh-server/
│       └── install-terminals/
├── pyproject.toml
├── README.md
└── multideck.config.json           # User config (same format, new `windows` field)
```

## 3. Config Schema

Backward-compatible with the existing JSON format. One new field: `windows`.

```python
from dataclasses import dataclass, field
from typing import Union

@dataclass
class LayoutConfig:
    columns: int = 2
    rows: int = 1

@dataclass
class SSHConfig:
    shell: str = "bash -lc"

@dataclass
class Settings:
    default_tool: str = "claude"
    settle_seconds: int = 3
    launch_delay_ms: int = 400
    ssh: SSHConfig = field(default_factory=SSHConfig)
    tools: dict[str, str] = field(default_factory=lambda: {
        "claude": "claude --continue",
        "codex": "codex",
    })

@dataclass
class ProjectConfig:
    path: str                                       # required
    group: str | None = None
    color: str | None = None                        # optional — terminal default if omitted
    tool: str | None = None                         # defaults to settings.default_tool
    title: str | None = None
    enabled: bool = True
    host: str | None = None                         # SSH remote target
    remote_path: str | None = None
    windows: int | list[str] | None = None          # NEW

@dataclass
class MultideckConfig:
    projects: list[ProjectConfig]
    base_dir: str | None = None
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    settings: Settings = field(default_factory=Settings)
```

### `windows` field behavior

- **Omitted or `1`**: current behavior, single window, tool command as-is.
- **`windows: N`** (number > 1): opens N windows. Titles auto-generated: `"api"`, `"api-2"`, `"api-3"`, ... where `"api"` is the base title (from `title` field or folder name).
- **`windows: ["feat", "bugs", "review"]`** (string array): opens one window per entry with the given custom title. Count inferred from array length.
- **Resume order**: window 1 gets the most recent session, window 2 the second most recent, etc. Windows beyond available sessions start fresh (no resume flag).
- **Ignored for**: `tool: "code"` (VS Code has no session resume), remote/SSH projects (no access to remote session storage).

### Example configs

```json
{
  "baseDir": "C:/Users/you/code",
  "layout": { "columns": 2, "rows": 1 },
  "settings": {
    "defaultTool": "claude",
    "settleSeconds": 3,
    "launchDelayMs": 400,
    "ssh": { "shell": "bash -lc" },
    "tools": {
      "claude": "claude --continue",
      "codex": "codex"
    }
  },
  "projects": [
    { "path": "internal/api", "group": "internal", "windows": 3 },
    { "path": "internal/web", "group": "internal", "windows": ["web-feat", "web-debug"] },
    { "path": "infra/terraform", "group": "infra", "tool": "codex" },
    { "path": "docs", "tool": "code" },
    { "host": "deploy@10.0.0.5", "path": "/srv/api", "group": "remote", "tool": "claude" }
  ]
}
```

## 4. Session Discovery

### 4.1 Claude (`sessions/claude.py`)

Claude stores sessions at `~/.claude/projects/<encoded-path>/<uuid>.jsonl`.

**Path encoding**: replace every character matching `[^a-zA-Z0-9._-]` with `-`. No collapsing of consecutive dashes.

Example:
```
C:\Users\amind\OneDrive\Desktop\Projects\CUSTOM MCPs & PRODUCTIVITY\multideck-ai-agent
→ C--Users-amind-OneDrive-Desktop-Projects-CUSTOM-MCPs---PRODUCTIVITY-multideck-ai-agent
```

**Discovery logic**:
1. Compute encoded path from the project's absolute directory.
2. List `~/.claude/projects/<encoded>/*.jsonl`.
3. Sort by file modification time, descending (most recent first).
4. Return the first N filenames (minus `.jsonl` extension) as session UUIDs.

```python
import re
from pathlib import Path

def encode_claude_project_path(project_dir: str) -> str:
    return re.sub(r'[^a-zA-Z0-9._-]', '-', project_dir)

def get_claude_session_ids(project_dir: str, count: int) -> list[str | None]:
    encoded = encode_claude_project_path(project_dir)
    sess_dir = Path.home() / ".claude" / "projects" / encoded
    if not sess_dir.is_dir():
        return [None] * count
    files = sorted(sess_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    ids: list[str | None] = [f.stem for f in files[:count]]
    while len(ids) < count:
        ids.append(None)
    return ids
```

### 4.2 Codex (`sessions/codex.py`)

Codex stores sessions at `~/.codex/sessions/YYYY/MM/DD/<name>-<timestamp>-<uuid>.jsonl`. Sessions are organized by date, not project. The first line of each `.jsonl` is a `session_meta` JSON object containing `payload.cwd`.

**Discovery logic**:
1. Recursively list `~/.codex/sessions/**/*.jsonl`.
2. Sort by file modification time, descending.
3. For each file (most recent first), read the first line, parse JSON, extract `payload.cwd`.
4. If `payload.cwd` matches the project directory (case-insensitive on Windows), collect `payload.id`.
5. Stop after collecting N matches.

```python
import json
import sys
from pathlib import Path

def get_codex_session_ids(project_dir: str, count: int) -> list[str | None]:
    sess_root = Path.home() / ".codex" / "sessions"
    if not sess_root.is_dir():
        return [None] * count
    case_insensitive = sys.platform == "win32"
    compare_dir = project_dir.lower() if case_insensitive else project_dir
    files = sorted(sess_root.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    ids: list[str | None] = []
    for f in files:
        if len(ids) >= count:
            break
        try:
            with open(f) as fh:
                meta = json.loads(fh.readline())
            cwd = meta.get("payload", {}).get("cwd", "")
            if case_insensitive:
                cwd = cwd.lower()
            if cwd == compare_dir:
                ids.append(meta["payload"]["id"])
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    while len(ids) < count:
        ids.append(None)
    return ids
```

**Performance**: reads only the first line of each file and stops early. Even with hundreds of sessions, this is sub-second.

### 4.3 Resume Command Construction

When `windows > 1`, the configured tool command's resume flags are stripped and replaced per-window:

```python
import re

def build_resume_command(tool: str, base_cmd: str, session_id: str | None) -> str:
    if tool == "claude":
        stripped = re.sub(r'--continue\s*', '', base_cmd)
        stripped = re.sub(r'--resume\s+\S+', '', stripped).strip()
        if session_id:
            return f"{stripped} --resume {session_id}"
        return stripped
    elif tool == "codex":
        parts = base_cmd.split(None, 1)
        binary = parts[0]  # "codex"
        if session_id:
            return f"{binary} resume {session_id}"
        return base_cmd
    return base_cmd
```

| Tool | Session found | No session |
|---|---|---|
| claude | Strip `--continue`/`--resume` from baseCmd, append `--resume <id>` | Strip `--continue`/`--resume` from baseCmd (fresh start) |
| codex | `codex resume <id>` | Use baseCmd as-is (fresh start) |

When `windows` is omitted (single window), the tool command is used exactly as configured — no modification.

## 5. Platform Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int

@dataclass
class MonitorRect(Rect):
    is_primary: bool = False
    scale_factor: float = 1.0       # 1.0 = 96 DPI, 1.5 = 144 DPI, etc.

@dataclass
class TerminalLaunchOpts:
    title: str
    cwd: str
    command: str
    color: str | None = None
    ssh_host: str | None = None
    ssh_remote_dir: str | None = None
    ssh_shell: str = "bash -lc"

@dataclass
class VSCodeLaunchOpts:
    dir: str
    ssh_host: str | None = None     # triggers --remote ssh-remote+<host>

class Platform(ABC):
    @abstractmethod
    def set_dpi_aware(self) -> None: ...

    @abstractmethod
    def list_monitors(self) -> list[MonitorRect]: ...

    @abstractmethod
    def find_window(self, title: str, mode: str = "exact") -> Any | None: ...

    @abstractmethod
    def move_window(self, handle: Any, rect: Rect) -> None: ...

    @abstractmethod
    def launch_terminal(self, opts: TerminalLaunchOpts) -> None: ...

    @abstractmethod
    def launch_vscode(self, opts: VSCodeLaunchOpts) -> None: ...
```

### 5.1 Windows (`platform/windows.py`)

Uses `ctypes` (built-in). Zero external dependencies.

| Operation | Win32 API via ctypes |
|---|---|
| DPI awareness | `ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)` with fallbacks to `ctypes.windll.shcore.SetProcessDpiAwareness(2)` and `ctypes.windll.user32.SetProcessDPIAware()` |
| Monitor enumeration | `EnumDisplayMonitors` callback + `GetMonitorInfoW` for working areas |
| DPI per monitor | `GetDpiForMonitor` (shcore.dll) |
| Window finding | `EnumWindows` callback + `GetWindowTextW` + `IsWindowVisible` |
| Window moving | `MoveWindow` called twice (cross-DPI correction) |
| Terminal launch | `subprocess.Popen(['wt', ...args])` |
| VS Code launch | `subprocess.Popen(['cmd', '/c', 'code', dir])` |

**ctypes setup** (example):

```python
import ctypes
import ctypes.wintypes
from ctypes import windll, POINTER, WINFUNCTYPE, byref, create_unicode_buffer

user32 = windll.user32
shcore = windll.shcore

# DPI awareness
def set_dpi_aware():
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (OSError, AttributeError):
        pass
    try:
        shcore.SetProcessDpiAwareness(2)
        return
    except (OSError, AttributeError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (OSError, AttributeError):
        pass

# Window enumeration
WNDENUMPROC = WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

def find_window_by_title(title: str, mode: str = "exact") -> int | None:
    result = None
    def callback(hwnd, _):
        nonlocal result
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if mode == "exact" and buf.value == title:
            result = hwnd
            return False
        if mode == "contains" and title.lower() in buf.value.lower():
            result = hwnd
            return False
        return True
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result

# Move window (called twice for cross-DPI correction)
def move_window(hwnd: int, x: int, y: int, w: int, h: int):
    user32.MoveWindow(hwnd, x, y, w, h, True)
    user32.MoveWindow(hwnd, x, y, w, h, True)
```

**Dual-MoveWindow for DPI**: when a window moves from monitor A to monitor B with a different scale factor, Windows fires `WM_DPICHANGED` and the window rescales itself mid-move. The first `MoveWindow` gets the window onto the target monitor; the second applies the correct size now that the window lives at the target DPI. Same-scale moves make the second call a no-op.

### 5.2 macOS (`platform/macos.py`)

Uses `subprocess` to call `osascript` (AppleScript) and small Swift snippets. Zero external dependencies.

| Operation | Implementation |
|---|---|
| DPI awareness | No-op (Retina handled by OS) |
| Monitor enumeration | Run Swift snippet via `subprocess`: `NSScreen.screens` → JSON with `frame`, `visibleFrame` (working area), and `backingScaleFactor` |
| Window finding | `osascript`: `tell application "System Events" to get name of every window of every process whose visible is true` |
| Window moving | `osascript`: `tell application "System Events" to tell process <P> to set position of window <W> to {x, y}` + `set size of window <W> to {w, h}` |
| Terminal launch | Detect installed terminal in priority order: iTerm2, Kitty, Warp, Terminal.app. Each adapter knows its CLI/AppleScript invocation. |
| VS Code launch | `subprocess.Popen(['code', dir])` or `code --remote ssh-remote+<host> <dir>` |

**Monitor enumeration Swift snippet** (run via `swift -e`):

```swift
import AppKit
import Foundation
var monitors: [[String: Any]] = []
for screen in NSScreen.screens {
    let f = screen.frame
    let v = screen.visibleFrame
    monitors.append([
        "x": Int(f.origin.x), "y": Int(f.origin.y),
        "w": Int(f.size.width), "h": Int(f.size.height),
        "work_x": Int(v.origin.x), "work_y": Int(v.origin.y),
        "work_w": Int(v.size.width), "work_h": Int(v.size.height),
        "scale": screen.backingScaleFactor
    ])
}
print(String(data: try! JSONSerialization.data(withJSONObject: monitors), encoding: .utf8)!)
```

**Terminal adapters (macOS)**:
- **iTerm2**: `osascript` to create new window with profile, set title, send command.
- **Kitty**: `kitty --title <t> --directory <d> <cmd>`
- **Warp**: `open -a Warp` + AppleScript for title/dir.
- **Terminal.app** (fallback): `osascript` to open new window, set cwd, run command.

### 5.3 Linux (`platform/linux.py`)

Requires X11 (Wayland support deferred — most CI and tiling use cases are X11). Dependencies: `xdotool`, `wmctrl`, `xrandr` (standard on most desktops; installed in CI).

| Operation | Implementation |
|---|---|
| DPI awareness | Read `Xft.dpi` via `subprocess.run(['xrdb', '-query'])` or `GDK_SCALE` env var. Compute scale factor. |
| Monitor enumeration | Parse `xrandr --query` for connected outputs: resolution, offset, physical size (mm) → compute DPI per monitor. Also support `xrandr --listmonitors` for virtual monitor setups. |
| Window finding | `subprocess.run(['xdotool', 'search', '--name', title])` (exact) or `wmctrl -l` + string matching (contains) |
| Window moving | `subprocess.run(['wmctrl', '-i', '-r', handle, '-e', f'0,{x},{y},{w},{h}'])` |
| Terminal launch | Detect installed terminal in priority order: kitty, alacritty, gnome-terminal, konsole, xterm. Each adapter knows its CLI flags. |
| VS Code launch | `subprocess.Popen(['code', dir])` |

**Terminal adapters (Linux)**:
- **kitty**: `kitty --title <t> --directory <d> <cmd>`
- **alacritty**: `alacritty --title <t> --working-directory <d> -e <cmd>`
- **gnome-terminal**: `gnome-terminal --title <t> --working-directory <d> -- <cmd>`
- **konsole**: `konsole --title <t> --workdir <d> -e <cmd>`
- **xterm** (fallback): `xterm -T <t> -e "cd <d> && <cmd>"`

### 5.4 Terminal Detection

Shared logic across macOS and Linux. Checks for terminal emulators in a priority-ordered list, returns the first found via `shutil.which()`:

```python
import shutil
from dataclasses import dataclass

@dataclass
class TerminalAdapter:
    name: str

    def detect(self) -> bool:
        return shutil.which(self.name) is not None

    def build_launch_args(self, opts: TerminalLaunchOpts) -> tuple[str, list[str]]:
        raise NotImplementedError
```

Windows always uses Windows Terminal (`wt`). macOS and Linux use the adapter registry. The detection result is cached for the duration of a run (via `functools.cache`).

## 6. Grid Computation (`grid.py`)

Pure function, no platform dependency. Takes monitor list + layout config, returns tile slots.

```python
from dataclasses import dataclass

@dataclass
class TileSlot(Rect):
    monitor_index: int = 0
    label: str = ""                 # "r1c1", "r1c2", etc.

def compute_grid(monitors: list[MonitorRect], cols: int, rows: int) -> list[TileSlot]:
    monitors_sorted = sorted(monitors, key=lambda m: m.x)
    slots: list[TileSlot] = []
    for i, m in enumerate(monitors_sorted):
        cell_w = m.w // cols
        cell_h = m.h // rows
        for r in range(rows):
            for c in range(cols):
                slots.append(TileSlot(
                    x=m.x + c * cell_w,
                    y=m.y + r * cell_h,
                    w=cell_w,
                    h=cell_h,
                    monitor_index=i,
                    label=f"r{r+1}c{c+1}",
                ))
    return slots
```

Logic:
1. Sort monitors by `x` position (left to right).
2. For each monitor, divide its working area into `cols × rows` cells.
3. Return all cells as `TileSlot` objects.
4. Windows wrap around to slot 0 when there are more windows than slots.

## 7. Launch Orchestrator (`launch.py`)

Central function that ties everything together:

```python
def run_multideck(config: MultideckConfig, opts: RunOpts) -> None
```

**Flow**:
1. Detect platform, call `set_dpi_aware()`.
2. Call `list_monitors()`, compute grid via `compute_grid()`.
3. Iterate projects (filtered by group/enabled):
   a. Resolve project path (relative to base_dir, env vars, `~`).
   b. Determine window count from `windows` field (default 1).
   c. If multi-window and tool is `claude`/`codex`: discover session IDs via `sessions/`.
   d. For each window instance:
      - Compute title (auto or custom).
      - Build tool command (with `--resume <id>` or fresh).
      - Check if window already exists via `find_window()`.
      - If not found and not dry-run: call `launch_terminal()` or `launch_vscode()`.
      - Add to tile queue.
4. Wait `settle_seconds` for new windows to appear.
5. Tile: for each window in the tile queue, call `find_window()` (with retry/polling) then `move_window()`.

**Idempotency**: windows already open (found by title) are skipped for launch but included in the tile queue when `--retile-all` is set.

## 8. CLI (`cli.py`)

Same flags as the PowerShell version, implemented with `click`:

```
Usage: multideck [OPTIONS]

Options:
  --go                    Skip interactive menu, launch + tile
  --retile-all            Re-tile every matching window
  --dry-run               Preview plan without launching or moving
  -g, --group TEXT        Launch only projects in this group
  --init                  Generate config by scanning a folder
  --base-dir PATH         Folder to scan with --init
  --config PATH           Path to config file (default: ./multideck.config.json)
  --force                 With --init, overwrite existing config
  --version               Print version
  --help                  Show help
```

Interactive menu when run with no flags (same choices as current PowerShell version). Uses Python's built-in `input()` for prompts in TTY mode.

## 9. PyPI Packaging

```toml
[project]
name = "multideck"
version = "1.0.0"
description = "Open every project in its own terminal and auto-tile across all monitors"
requires-python = ">=3.10"
dependencies = ["click>=8.0"]

[project.scripts]
multideck = "multideck.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "platform: platform integration tests (require virtual displays)",
    "e2e: end-to-end tests (full pipeline)",
]

[tool.hatch.build.targets.wheel]
packages = ["src/multideck"]
```

**Zero native dependencies.** The only runtime dependency is `click`. Everything else (`ctypes`, `subprocess`, `json`, `pathlib`, `re`, `shutil`, `os`) is in Python's standard library.

Install and run:
```bash
pip install multideck
multideck --go

# or without install:
pipx run multideck --go

# or from source:
python -m multideck --go
```

## 10. CI/CD Pipeline

### 10.1 GitHub Actions Matrix

```yaml
name: CI
on: [push, pull_request]

jobs:
  unit:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
        python: ["3.10", "3.11", "3.12", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ -v

  platform:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - name: Setup virtual displays
        uses: ./.github/actions/setup-virtual-displays
      - name: Install terminal emulators
        uses: ./.github/actions/install-terminals
      - run: pytest tests/platform/ -v -m platform

  e2e:
    strategy:
      matrix:
        os: [windows-latest, macos-latest, ubuntu-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - name: Setup virtual displays
        uses: ./.github/actions/setup-virtual-displays
      - name: Setup SSH server
        uses: ./.github/actions/setup-ssh-server
      - name: Install terminal emulators
        uses: ./.github/actions/install-terminals
      - run: pytest tests/e2e/ -v -m e2e

  packaging:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install build
      - run: python -m build
      - run: pip install dist/multideck-*.whl
      - run: multideck --help
      - run: multideck --version
```

### 10.2 CI Setup Actions

**`.github/actions/setup-virtual-displays`** — creates multi-monitor + multi-DPI environments:

- **Linux**: Start `Xvfb :99 -screen 0 5760x2160x24`, then use `xrandr --setmonitor` to carve out virtual monitors at different physical sizes (simulating different DPIs). Install `wmctrl`, `xdotool`. Export `DISPLAY=:99`.
- **Windows**: Install a virtual display driver (IddCx-based or `virtual-display-rs`) to create a second virtual monitor. Set per-monitor DPI via registry under `HKCU\Control Panel\Desktop\PerMonitorSettings`.
- **macOS**: Use `CGVirtualDisplay` or system preferences scripting to configure a second virtual display. Query `NSScreen` to verify.

**`.github/actions/setup-ssh-server`** — starts a local SSH server:

- **Linux**: `apt-get install openssh-server`, generate ed25519 key, add to `authorized_keys`, start `sshd` on a non-standard port. Export `MULTIDECK_TEST_SSH_PORT`.
- **Windows**: Enable OpenSSH Server optional feature, configure and start `sshd`.
- **macOS**: `sudo systemsetup -setremotelogin on`, generate key, add to `authorized_keys`.

**`.github/actions/install-terminals`** — installs multiple terminal emulators:

- **Linux**: `apt-get install xterm gnome-terminal kitty`
- **macOS**: `brew install --cask iterm2 kitty`
- **Windows**: Windows Terminal is pre-installed; no action needed.

### 10.3 Complete Test Matrix

#### Unit Tests (all 3 OS × Python 3.10-3.13, no special setup)

| Area | Tests |
|---|---|
| Config parsing | Valid JSON, invalid JSON, missing required fields, wrong types, proper error messages |
| Config defaults | Each optional field omitted → correct default applied |
| Path resolution | Relative, absolute, `~`, env vars, forward slashes, backslashes |
| Group filtering | Filter by group name, empty group, non-existent group |
| `enabled: false` | Disabled projects excluded |
| Custom tools | Register tool in settings.tools, verify command resolved |
| `windows: N` | 1, 2, 5 → correct number of launch entries with auto-titles |
| `windows: [...]` | String array → correct titles, count from length |
| `windows` omitted | Single window, backward-compatible |
| `windows` + `tool: "code"` | Ignored, single VS Code window |
| `windows` + remote/SSH | Ignored, single window |
| Grid: 1 monitor, 2×1 | 2 slots, correct coordinates |
| Grid: 1 monitor, 2×2 | 4 slots |
| Grid: 2 monitors, different sizes | Correct per-monitor slot dimensions |
| Grid: 3 monitors, mixed res | 1080p + 1440p + 4K |
| Grid: taskbar offset | WorkingArea ≠ Bounds |
| Grid: more windows than slots | Wraps to slot 0 |
| Claude path encoding | Known paths → expected encoded strings |
| Claude session scan | Fixture dir with N files, controlled mtimes → correct order |
| Codex session scan | Fixtures with mixed CWDs → only matching CWDs returned |
| Session: fewer than requested | Request 5, only 2 → 2 IDs + 3 nulls |
| Session: zero available | Empty dir → all nulls |
| Title gen: auto | "api" → "api", "api-2", "api-3" |
| Title gen: custom | Array titles used verbatim |
| Title gen: from folder name | No `title` field → leaf of path |
| Title gen: duplicate leaves | Detected during --init, unique titles generated |
| Resume cmd: claude, session found | `claude --resume <id>` |
| Resume cmd: claude, fresh | `claude` (no resume flag) |
| Resume cmd: codex, session found | `codex resume <id>` |
| Resume cmd: codex, fresh | `codex` (no resume flag) |
| Resume cmd: strips --continue | Base cmd `claude --continue` → `claude --resume <id>` |
| SSH command construction | Full SSH command string with shell wrapper |
| SSH shell wrapper disabled | Empty string → no wrapper |
| Remote dir resolution | `remotePath` takes precedence over `path` |
| Init: folder scanning | Temp dir with git repos → correct config |
| Init: duplicate leaf names | Unique titles generated |
| Init: no git repos fallback | Falls back to immediate subdirectories |

#### Platform Integration Tests (per-OS, with virtual displays + terminals)

| Area | Tests |
|---|---|
| `list_monitors()` ≥ 1 | At least 1 monitor with valid bounds |
| `list_monitors()` multi-monitor | Virtual monitors → correct count and geometries |
| `list_monitors()` DPI per monitor | Different physical sizes → different scale factors |
| `find_window()` exact match | Launch window, find by exact title |
| `find_window()` contains match | Launch with compound title, find by substring |
| `find_window()` miss | Non-existent title → None |
| `move_window()` reposition | Move window, re-query, assert new position |
| `move_window()` cross-DPI | Move from 96 DPI to 180 DPI monitor, verify correct final size |
| Terminal launch: primary | Launch with OS default terminal, verify window appears with title |
| Terminal launch: each adapter | Launch with each installed terminal, verify title and cwd |
| Terminal detection | With multiple installed, correct priority order |
| Terminal cwd | Verify terminal opens in correct directory |
| Terminal color | Verify color arg included (where supported) |
| VS Code launch | `code <dir>`, verify window with folder name in title |
| VS Code Remote-SSH | `code --remote ssh-remote+localhost <dir>` via local SSH |
| VS Code title matching | Title contains folder basename |
| VS Code async polling | Launch, poll with timeout, verify found |

#### E2E Tests (per-OS, full pipeline)

| Area | Tests |
|---|---|
| Basic launch | Config with 2 projects → 2 windows with correct titles |
| `windows: 3` | 3 windows spawned: "api", "api-2", "api-3" |
| `windows: ["a","b"]` | 2 windows with custom titles |
| Session resume | Plant 3 fixture sessions, verify each window got correct `--resume <id>` |
| Excess windows fresh | 3 windows, 1 session → 1 resume + 2 fresh |
| Tiling positions | Windows placed at expected grid coordinates |
| Multi-monitor tiling | Windows distributed across virtual monitors |
| Idempotent re-run | Run twice → no duplicate windows |
| `--go` flag | Launches without interactive menu |
| `--group` flag | Only matching group launched |
| `--dry-run` | Zero windows spawned, plan output printed |
| `--retile-all` | Already-open windows repositioned |
| `--init` | Scans temp folder, writes valid config |
| `--config <path>` | Uses alternate config file |
| `--force` with `--init` | Overwrites existing config |
| Interactive menu | Use `pexpect` to simulate TTY + keypress sequences |
| No config found | Error message + prompt |
| SSH launch | Real SSH to localhost, terminal opens with remote command |
| SSH `cmd /k` persistence (Windows) | Window stays open after SSH session ends |
| SSH missing warning | Remove SSH from PATH, assert warning |
| Mixed tools | Config with claude + codex + code → each launched correctly |
| Empty config | No projects → graceful message |
| Invalid config | Malformed JSON → clear error |
| Unknown tool | Warning, project skipped |

#### Packaging Tests (ubuntu)

| Area | Tests |
|---|---|
| `python -m build` | Produces wheel + sdist |
| Install from wheel | `pip install dist/multideck-*.whl` succeeds |
| `multideck --help` | Exits 0, shows usage text |
| `multideck --version` | Prints version string |
| Entry point resolves | `which multideck` points to installed script |

## 11. Migration from PowerShell

The Python version reads the same `multideck.config.json` format. Existing configs work without modification. The `windows` field is optional and additive. JSON keys use `camelCase` in the config file (matching the existing format); Python dataclasses use `snake_case` internally with conversion during parsing.

Users replace:
```
.\multideck.bat           →  multideck
.\multideck.bat -Go       →  multideck --go
.\multideck.bat -Group x  →  multideck -g x
```

The PowerShell scripts (`scripts/multideck.ps1`, `scripts/multideck.lib.ps1`) and batch launcher (`multideck.bat`) remain in the repo but are deprecated. They can be removed in a future release.

## 12. Dependencies

### Runtime

| Package | Purpose | Notes |
|---|---|---|
| `click` | CLI parsing | Pure Python, mature, widely used |

Everything else is Python standard library: `ctypes` (Win32), `subprocess` (process launching), `json` (config/session parsing), `pathlib` (file operations), `re` (string processing), `shutil` (terminal detection), `os`/`sys` (platform detection), `functools` (caching), `dataclasses` (data structures).

### Development

| Package | Purpose |
|---|---|
| `pytest` | Test framework |
| `pexpect` | Interactive menu testing (TTY simulation) |
| `pyright` | Static type checking |

## 13. Decisions & Trade-offs

| Decision | Rationale |
|---|---|
| `ctypes` over `pywin32` | Built-in, zero install, sufficient for the Win32 APIs we need |
| `click` over `argparse` | Cleaner API, better UX for interactive prompts, well-maintained |
| `pytest` over `unittest` | Fixtures, parameterize, markers, cleaner syntax |
| `subprocess` over native bindings | No native deps on macOS/Linux, sufficient for AppleScript + xdotool/wmctrl |
| Swift snippet for macOS monitors | `NSScreen` is the authoritative source; a 10-line snippet is simpler than `pyobjc` |
| `xdotool`/`wmctrl` for Linux | Standard desktop tools, no native deps, sufficient for tiling |
| AppleScript for macOS window ops | No native addon needed, works for find/move |
| File scanning for sessions | Neither Claude nor Codex has a non-interactive session list command |
| Resume all windows with `--resume <id>` | Consistent ordering controlled by our scan, avoids `--continue` mismatch |
| X11 only (no Wayland) for v1 | Most tiling use cases and CI environments use X11; Wayland is WM-dependent |
| Python 3.10+ minimum | Required for `match` statements, `X | Y` union types, `dataclass(slots=True)` |
| `hatchling` build backend | Fast, minimal config, widely adopted |

## 14. Future Work (out of scope for this implementation)

- Wayland support (Linux) — requires compositor-specific protocols (sway IPC, KWin scripting).
- Multi-window for remote/SSH projects — would need SSH tunnel to scan remote session files.
- Session naming / pinning — let users pin a specific session ID to a window slot.
- Auto-color assignment — assign colors from a palette when `color` is omitted.
- Config hot-reload — watch config file, re-tile on change.
