# Multideck Python Rewrite + Multi-Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite multideck from PowerShell to Python with cross-platform support (Windows/macOS/Linux), multi-window session resume, and PyPI publishing.

**Architecture:** Python CLI tool using `click` for CLI parsing, `ctypes` for Win32 APIs (Windows), `subprocess`+`osascript` for macOS, `subprocess`+`xdotool`/`wmctrl`/`xrandr` for Linux. Session discovery scans `~/.claude/projects/` and `~/.codex/sessions/` to find conversation UUIDs for `--resume` flags. Grid computation is a pure function mapping monitors to tile slots.

**Tech Stack:** Python 3.10+, click (CLI), ctypes (Win32), pytest (testing), hatchling (packaging)

**Spec:** `docs/superpowers/specs/2026-06-23-node-rewrite-multi-window-design.md`

---

## File Structure

```
src/multideck/
  __init__.py           — version string
  __main__.py           — python -m multideck entry point
  cli.py                — click CLI with --go, --retile-all, --dry-run, --group, --init, etc.
  config.py             — Config loading, camelCase→snake_case, validation, dataclasses
  grid.py               — Pure grid computation: monitors × cols × rows → TileSlot list
  launch.py             — Orchestrator: discover sessions, build commands, launch, tile
  titles.py             — Title generation for single and multi-window projects
  init_config.py        — Folder scanning + config generation (--init)
  terminals.py          — Terminal emulator detection + per-terminal launch arg builders
  sessions/
    __init__.py          — build_resume_command() dispatcher
    claude.py            — Claude session discovery (file-system scan)
    codex.py             — Codex session discovery (first-line CWD matching)
  platform/
    __init__.py          — ABC Platform, Rect, MonitorRect, TerminalLaunchOpts, VSCodeLaunchOpts, get_platform()
    windows.py           — Win32 via ctypes
    macos.py             — CoreGraphics + AppleScript via subprocess
    linux.py             — xrandr + xdotool/wmctrl via subprocess

tests/
  conftest.py            — Shared fixtures (tmp dirs, fake session files)
  unit/
    test_config.py       — Config parsing, defaults, validation, path resolution
    test_grid.py         — Grid computation with various monitor layouts
    test_sessions.py     — Claude + Codex session discovery with fixture files
    test_titles.py       — Title generation: auto, custom, folder-name, duplicates
    test_commands.py     — Resume command construction for claude/codex
  platform/
    test_monitors.py     — list_monitors() returns valid data on current OS
    test_windows.py      — find_window() + move_window() with real windows
    test_terminals.py    — Terminal detection + launch on current OS
  e2e/
    test_launch.py       — Full pipeline: config → launch → tile
    test_multi_window.py — Multi-window session resume e2e
    test_ssh.py          — SSH launch via local SSH server
    test_idempotency.py  — Re-run doesn't duplicate windows
    test_cli_flags.py    — All CLI flags and interactive menu
  fixtures/
    claude_sessions/     — Fake .jsonl files with controlled mtimes
    codex_sessions/      — Fake .jsonl files with CWD metadata
  helpers/
    virtual_display.py   — Setup/teardown virtual monitors in CI
    ssh_server.py        — Setup/teardown local SSH server
    poll.py              — Retry-with-timeout for async window discovery

.github/
  workflows/ci.yml                       — Matrix: os × python × test-tier
  actions/setup-virtual-displays/action.yml
  actions/setup-ssh-server/action.yml
  actions/install-terminals/action.yml

pyproject.toml
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/multideck/__init__.py`
- Create: `src/multideck/__main__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "multideck"
version = "1.0.0"
description = "Open every project in its own terminal and auto-tile across all monitors"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
dependencies = ["click>=8.0"]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pexpect>=4.8"]

[project.scripts]
multideck = "multideck.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/multideck"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "platform: platform integration tests (require virtual displays)",
    "e2e: end-to-end tests (full pipeline)",
]
```

- [ ] **Step 2: Create `src/multideck/__init__.py`**

```python
__version__ = "1.0.0"
```

- [ ] **Step 3: Create `src/multideck/__main__.py`**

```python
from multideck.cli import main

main()
```

- [ ] **Step 4: Create `tests/__init__.py` and `tests/conftest.py`**

`tests/__init__.py` — empty file.

`tests/conftest.py`:

```python
import json
import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path):
    """Write a config dict to a temp JSON file and return the path."""
    def _write(config_dict):
        p = tmp_path / "multideck.config.json"
        p.write_text(json.dumps(config_dict))
        return str(p)
    return _write


@pytest.fixture
def fake_claude_sessions(tmp_path):
    """Create fake Claude session .jsonl files with controlled mtimes.

    Usage: fake_claude_sessions(encoded_path, [("uuid1", mtime1), ("uuid2", mtime2)])
    Returns the sessions directory path.
    """
    def _create(encoded_path, sessions):
        sess_dir = tmp_path / ".claude" / "projects" / encoded_path
        sess_dir.mkdir(parents=True, exist_ok=True)
        for uuid, mtime in sessions:
            f = sess_dir / f"{uuid}.jsonl"
            f.write_text('{"type":"message"}\n')
            os.utime(f, (mtime, mtime))
        return sess_dir
    return _create


@pytest.fixture
def fake_codex_sessions(tmp_path):
    """Create fake Codex session .jsonl files with CWD metadata.

    Usage: fake_codex_sessions([("/path/to/project", "uuid1", mtime1), ...])
    Returns the sessions root directory path.
    """
    def _create(sessions):
        sess_root = tmp_path / ".codex" / "sessions"
        for i, (cwd, uuid, mtime) in enumerate(sessions):
            day_dir = sess_root / "2026" / "06" / str(20 + i)
            day_dir.mkdir(parents=True, exist_ok=True)
            meta = {"timestamp": "2026-06-20T00:00:00Z", "type": "session_meta",
                    "payload": {"id": uuid, "cwd": cwd}}
            f = day_dir / f"session-{i}-{uuid}.jsonl"
            f.write_text(json.dumps(meta) + "\n")
            os.utime(f, (mtime, mtime))
        return sess_root
    return _create
```

- [ ] **Step 5: Create empty directories**

```bash
mkdir -p src/multideck/sessions src/multideck/platform tests/unit tests/platform tests/e2e tests/fixtures/claude_sessions tests/fixtures/codex_sessions tests/helpers
```

Create empty `__init__.py` files:

- `src/multideck/sessions/__init__.py`
- `src/multideck/platform/__init__.py`
- `tests/unit/__init__.py`
- `tests/platform/__init__.py`
- `tests/e2e/__init__.py`
- `tests/helpers/__init__.py`

- [ ] **Step 6: Verify install**

Run: `pip install -e ".[dev]"`
Expected: installs successfully, `multideck` command available (will fail at import until cli.py exists — that's fine).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "scaffold: Python project structure with pyproject.toml and test fixtures"
```

---

### Task 2: Config Data Models + Loading

**Files:**
- Create: `src/multideck/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing tests for config parsing**

`tests/unit/test_config.py`:

```python
import json
import pytest
from multideck.config import load_config, MultideckConfig, ProjectConfig


class TestLoadConfig:
    def test_minimal_valid_config(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api"}]})
        cfg = load_config(path)
        assert isinstance(cfg, MultideckConfig)
        assert len(cfg.projects) == 1
        assert cfg.projects[0].path == "api"

    def test_full_config(self, tmp_config):
        path = tmp_config({
            "baseDir": "C:/code",
            "layout": {"columns": 3, "rows": 2},
            "settings": {
                "defaultTool": "codex",
                "settleSeconds": 5,
                "launchDelayMs": 200,
                "ssh": {"shell": "zsh -lc"},
                "tools": {"claude": "claude --continue", "codex": "codex --yolo"},
            },
            "projects": [
                {"path": "api", "group": "backend", "color": "#ff0000",
                 "tool": "claude", "title": "my-api", "enabled": True,
                 "host": None, "remotePath": None, "windows": 3},
            ],
        })
        cfg = load_config(path)
        assert cfg.base_dir == "C:/code"
        assert cfg.layout.columns == 3
        assert cfg.layout.rows == 2
        assert cfg.settings.default_tool == "codex"
        assert cfg.settings.settle_seconds == 5
        assert cfg.settings.launch_delay_ms == 200
        assert cfg.settings.ssh.shell == "zsh -lc"
        assert cfg.settings.tools["codex"] == "codex --yolo"
        p = cfg.projects[0]
        assert p.group == "backend"
        assert p.color == "#ff0000"
        assert p.windows == 3

    def test_defaults_applied(self, tmp_config):
        path = tmp_config({"projects": [{"path": "x"}]})
        cfg = load_config(path)
        assert cfg.base_dir is None
        assert cfg.layout.columns == 2
        assert cfg.layout.rows == 1
        assert cfg.settings.default_tool == "claude"
        assert cfg.settings.settle_seconds == 3
        assert cfg.settings.launch_delay_ms == 400
        assert cfg.settings.ssh.shell == "bash -lc"
        assert "claude" in cfg.settings.tools

    def test_windows_as_string_array(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api", "windows": ["feat", "bugs"]}]})
        cfg = load_config(path)
        assert cfg.projects[0].windows == ["feat", "bugs"]

    def test_windows_omitted_is_none(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api"}]})
        cfg = load_config(path)
        assert cfg.projects[0].windows is None

    def test_enabled_defaults_true(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api"}]})
        cfg = load_config(path)
        assert cfg.projects[0].enabled is True

    def test_enabled_false(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api", "enabled": False}]})
        cfg = load_config(path)
        assert cfg.projects[0].enabled is False

    def test_missing_projects_raises(self, tmp_config):
        path = tmp_config({"layout": {"columns": 2}})
        with pytest.raises(ValueError, match="projects"):
            load_config(path)

    def test_project_missing_path_raises(self, tmp_config):
        path = tmp_config({"projects": [{"group": "x"}]})
        with pytest.raises(ValueError, match="path"):
            load_config(path)

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json{{{")
        with pytest.raises(ValueError, match="valid JSON"):
            load_config(str(p))

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.json")


class TestPathResolution:
    def test_resolve_relative(self, tmp_config):
        path = tmp_config({
            "baseDir": "/home/user/code",
            "projects": [{"path": "api"}],
        })
        cfg = load_config(path)
        assert cfg.projects[0].path == "api"

    def test_resolve_absolute(self, tmp_config):
        path = tmp_config({"projects": [{"path": "/absolute/path"}]})
        cfg = load_config(path)
        assert cfg.projects[0].path == "/absolute/path"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'multideck.config'`

- [ ] **Step 3: Implement config.py**

`src/multideck/config.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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
    path: str
    group: str | None = None
    color: str | None = None
    tool: str | None = None
    title: str | None = None
    enabled: bool = True
    host: str | None = None
    remote_path: str | None = None
    windows: int | list[str] | None = None


@dataclass
class MultideckConfig:
    projects: list[ProjectConfig]
    base_dir: str | None = None
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    settings: Settings = field(default_factory=Settings)


def _parse_ssh(raw: dict | None) -> SSHConfig:
    if not raw:
        return SSHConfig()
    return SSHConfig(shell=raw.get("shell", "bash -lc"))


def _parse_settings(raw: dict | None) -> Settings:
    if not raw:
        return Settings()
    return Settings(
        default_tool=raw.get("defaultTool", "claude"),
        settle_seconds=raw.get("settleSeconds", 3),
        launch_delay_ms=raw.get("launchDelayMs", 400),
        ssh=_parse_ssh(raw.get("ssh")),
        tools=raw.get("tools", {"claude": "claude --continue", "codex": "codex"}),
    )


def _parse_project(raw: dict) -> ProjectConfig:
    if "path" not in raw:
        raise ValueError("Each project must have a 'path' field")
    return ProjectConfig(
        path=raw["path"],
        group=raw.get("group"),
        color=raw.get("color"),
        tool=raw.get("tool"),
        title=raw.get("title"),
        enabled=raw.get("enabled", True),
        host=raw.get("host"),
        remote_path=raw.get("remotePath"),
        windows=raw.get("windows"),
    )


def load_config(path: str) -> MultideckConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    text = config_path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Config is not valid JSON: {e}") from e

    if "projects" not in raw or not isinstance(raw["projects"], list):
        raise ValueError("Config must have a 'projects' array")

    layout_raw = raw.get("layout", {})
    layout = LayoutConfig(
        columns=max(1, layout_raw.get("columns", 2)),
        rows=max(1, layout_raw.get("rows", 1)),
    )

    return MultideckConfig(
        projects=[_parse_project(p) for p in raw["projects"]],
        base_dir=raw.get("baseDir"),
        layout=layout,
        settings=_parse_settings(raw.get("settings")),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_config.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/multideck/config.py tests/unit/test_config.py
git commit -m "feat: config dataclasses and JSON loader with camelCase conversion"
```

---

### Task 3: Grid Computation

**Files:**
- Create: `src/multideck/grid.py`
- Create: `tests/unit/test_grid.py`

- [ ] **Step 1: Write failing tests for grid computation**

`tests/unit/test_grid.py`:

```python
from multideck.grid import compute_grid, TileSlot, Rect, MonitorRect


def _mon(x, y, w, h, primary=False, scale=1.0):
    return MonitorRect(x=x, y=y, w=w, h=h, is_primary=primary, scale_factor=scale)


class TestComputeGrid:
    def test_single_monitor_2x1(self):
        monitors = [_mon(0, 0, 1920, 1080, primary=True)]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert len(slots) == 2
        assert slots[0] == TileSlot(x=0, y=0, w=960, h=1080, monitor_index=0, label="r1c1")
        assert slots[1] == TileSlot(x=960, y=0, w=960, h=1080, monitor_index=0, label="r1c2")

    def test_single_monitor_2x2(self):
        monitors = [_mon(0, 0, 1920, 1080)]
        slots = compute_grid(monitors, cols=2, rows=2)
        assert len(slots) == 4
        assert slots[0] == TileSlot(x=0, y=0, w=960, h=540, monitor_index=0, label="r1c1")
        assert slots[1] == TileSlot(x=960, y=0, w=960, h=540, monitor_index=0, label="r1c2")
        assert slots[2] == TileSlot(x=0, y=540, w=960, h=540, monitor_index=0, label="r2c1")
        assert slots[3] == TileSlot(x=960, y=540, w=960, h=540, monitor_index=0, label="r2c2")

    def test_two_monitors_different_sizes(self):
        monitors = [_mon(0, 0, 1920, 1080), _mon(1920, 0, 2560, 1440)]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert len(slots) == 4
        # First monitor
        assert slots[0].x == 0
        assert slots[0].w == 960
        assert slots[1].x == 960
        assert slots[1].w == 960
        # Second monitor
        assert slots[2].x == 1920
        assert slots[2].w == 1280
        assert slots[3].x == 1920 + 1280
        assert slots[3].w == 1280

    def test_monitors_sorted_by_x(self):
        monitors = [_mon(1920, 0, 1920, 1080), _mon(0, 0, 1920, 1080)]
        slots = compute_grid(monitors, cols=1, rows=1)
        assert slots[0].x == 0
        assert slots[0].monitor_index == 0
        assert slots[1].x == 1920
        assert slots[1].monitor_index == 1

    def test_taskbar_offset(self):
        monitors = [_mon(0, 40, 1920, 1040)]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert slots[0].y == 40
        assert slots[0].h == 1040

    def test_three_monitors_mixed_res(self):
        monitors = [
            _mon(0, 0, 1920, 1080),
            _mon(1920, 0, 2560, 1440),
            _mon(4480, 0, 3840, 2160),
        ]
        slots = compute_grid(monitors, cols=2, rows=1)
        assert len(slots) == 6

    def test_1x1_grid(self):
        monitors = [_mon(0, 0, 1920, 1080)]
        slots = compute_grid(monitors, cols=1, rows=1)
        assert len(slots) == 1
        assert slots[0] == TileSlot(x=0, y=0, w=1920, h=1080, monitor_index=0, label="r1c1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_grid.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement grid.py**

`src/multideck/grid.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass
class MonitorRect(Rect):
    is_primary: bool = False
    scale_factor: float = 1.0


@dataclass
class TileSlot(Rect):
    monitor_index: int = 0
    label: str = ""


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
                    label=f"r{r + 1}c{c + 1}",
                ))
    return slots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_grid.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/multideck/grid.py tests/unit/test_grid.py
git commit -m "feat: grid computation — monitors × cols × rows → tile slots"
```

---

### Task 4: Claude Session Discovery

**Files:**
- Create: `src/multideck/sessions/claude.py`
- Create: `tests/unit/test_sessions.py`

- [ ] **Step 1: Write failing tests for Claude session discovery**

`tests/unit/test_sessions.py`:

```python
import os
import pytest
from multideck.sessions.claude import encode_claude_project_path, get_claude_session_ids


class TestEncodeClaudeProjectPath:
    def test_windows_path(self):
        result = encode_claude_project_path(
            r"C:\Users\amind\OneDrive\Desktop\Projects\CUSTOM MCPs & PRODUCTIVITY\multideck-ai-agent"
        )
        assert result == "C--Users-amind-OneDrive-Desktop-Projects-CUSTOM-MCPs---PRODUCTIVITY-multideck-ai-agent"

    def test_unix_path(self):
        result = encode_claude_project_path("/home/user/code/my-project")
        assert result == "-home-user-code-my-project"

    def test_preserves_dots_and_dashes(self):
        result = encode_claude_project_path("my-project.v2")
        assert result == "my-project.v2"

    def test_spaces_become_dashes(self):
        result = encode_claude_project_path("my project")
        assert result == "my-project"

    def test_consecutive_special_chars_not_collapsed(self):
        result = encode_claude_project_path("a&&b")
        assert result == "a--b"


class TestGetClaudeSessionIds:
    def test_returns_ids_sorted_by_mtime(self, fake_claude_sessions):
        encoded = "test-project"
        fake_claude_sessions(encoded, [
            ("uuid-oldest", 1000.0),
            ("uuid-newest", 3000.0),
            ("uuid-middle", 2000.0),
        ])
        ids = get_claude_session_ids("test-project", 3, home_override=fake_claude_sessions.__wrapped_tmp)
        assert ids == ["uuid-newest", "uuid-middle", "uuid-oldest"]

    def test_returns_fewer_than_requested(self, fake_claude_sessions):
        encoded = "test-project"
        fake_claude_sessions(encoded, [("uuid-1", 1000.0), ("uuid-2", 2000.0)])
        ids = get_claude_session_ids("test-project", 5, home_override=fake_claude_sessions.__wrapped_tmp)
        assert ids == ["uuid-2", "uuid-1", None, None, None]

    def test_empty_dir(self, fake_claude_sessions):
        fake_claude_sessions("test-project", [])
        ids = get_claude_session_ids("test-project", 3, home_override=fake_claude_sessions.__wrapped_tmp)
        assert ids == [None, None, None]

    def test_no_dir_exists(self, tmp_path):
        ids = get_claude_session_ids("nonexistent", 2, home_override=tmp_path)
        assert ids == [None, None]

    def test_count_one(self, fake_claude_sessions):
        encoded = "test-project"
        fake_claude_sessions(encoded, [("uuid-1", 1000.0), ("uuid-2", 2000.0)])
        ids = get_claude_session_ids("test-project", 1, home_override=fake_claude_sessions.__wrapped_tmp)
        assert ids == ["uuid-2"]
```

- [ ] **Step 2: Update conftest.py to attach tmp_path to the fixture**

Add attribute access to the `fake_claude_sessions` fixture so tests can pass the home directory. Update `tests/conftest.py` — change the `fake_claude_sessions` fixture:

```python
@pytest.fixture
def fake_claude_sessions(tmp_path):
    """Create fake Claude session .jsonl files with controlled mtimes."""
    def _create(encoded_path, sessions):
        sess_dir = tmp_path / ".claude" / "projects" / encoded_path
        sess_dir.mkdir(parents=True, exist_ok=True)
        for uuid, mtime in sessions:
            f = sess_dir / f"{uuid}.jsonl"
            f.write_text('{"type":"message"}\n')
            os.utime(f, (mtime, mtime))
        return sess_dir
    _create.__wrapped_tmp = tmp_path
    return _create
```

Do the same for `fake_codex_sessions`:

```python
@pytest.fixture
def fake_codex_sessions(tmp_path):
    """Create fake Codex session .jsonl files with CWD metadata."""
    def _create(sessions):
        sess_root = tmp_path / ".codex" / "sessions"
        for i, (cwd, uuid, mtime) in enumerate(sessions):
            day_dir = sess_root / "2026" / "06" / str(20 + i)
            day_dir.mkdir(parents=True, exist_ok=True)
            meta = {"timestamp": "2026-06-20T00:00:00Z", "type": "session_meta",
                    "payload": {"id": uuid, "cwd": cwd}}
            f = day_dir / f"session-{i}-{uuid}.jsonl"
            f.write_text(json.dumps(meta) + "\n")
            os.utime(f, (mtime, mtime))
        return sess_root
    _create.__wrapped_tmp = tmp_path
    return _create
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_sessions.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement `sessions/claude.py`**

`src/multideck/sessions/claude.py`:

```python
from __future__ import annotations

import re
from pathlib import Path


def encode_claude_project_path(project_dir: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "-", project_dir)


def get_claude_session_ids(
    project_dir: str,
    count: int,
    home_override: Path | None = None,
) -> list[str | None]:
    encoded = encode_claude_project_path(project_dir)
    home = home_override or Path.home()
    sess_dir = home / ".claude" / "projects" / encoded

    if not sess_dir.is_dir():
        return [None] * count

    files = sorted(
        sess_dir.glob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    ids: list[str | None] = [f.stem for f in files[:count]]
    while len(ids) < count:
        ids.append(None)
    return ids
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_sessions.py -v`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/multideck/sessions/claude.py tests/unit/test_sessions.py tests/conftest.py
git commit -m "feat: Claude session discovery — scan ~/.claude/projects/ by mtime"
```

---

### Task 5: Codex Session Discovery

**Files:**
- Modify: `src/multideck/sessions/codex.py`
- Modify: `tests/unit/test_sessions.py`

- [ ] **Step 1: Write failing tests for Codex session discovery**

Add to `tests/unit/test_sessions.py`:

```python
import sys
from multideck.sessions.codex import get_codex_session_ids


class TestGetCodexSessionIds:
    def test_returns_matching_sessions_sorted_by_mtime(self, fake_codex_sessions):
        fake_codex_sessions([
            ("/home/user/api", "uuid-oldest", 1000.0),
            ("/home/user/api", "uuid-newest", 3000.0),
            ("/home/user/other", "uuid-other", 2000.0),
            ("/home/user/api", "uuid-middle", 2000.0),
        ])
        ids = get_codex_session_ids(
            "/home/user/api", 3,
            home_override=fake_codex_sessions.__wrapped_tmp,
        )
        assert ids == ["uuid-newest", "uuid-middle", "uuid-oldest"]

    def test_case_insensitive_on_windows(self, fake_codex_sessions, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        fake_codex_sessions([
            ("C:\\Users\\User\\api", "uuid-1", 1000.0),
        ])
        ids = get_codex_session_ids(
            "c:\\users\\user\\api", 1,
            home_override=fake_codex_sessions.__wrapped_tmp,
        )
        assert ids == ["uuid-1"]

    def test_fewer_than_requested(self, fake_codex_sessions):
        fake_codex_sessions([
            ("/home/user/api", "uuid-1", 1000.0),
        ])
        ids = get_codex_session_ids(
            "/home/user/api", 3,
            home_override=fake_codex_sessions.__wrapped_tmp,
        )
        assert ids == ["uuid-1", None, None]

    def test_no_matching_sessions(self, fake_codex_sessions):
        fake_codex_sessions([
            ("/home/user/other", "uuid-1", 1000.0),
        ])
        ids = get_codex_session_ids(
            "/home/user/api", 2,
            home_override=fake_codex_sessions.__wrapped_tmp,
        )
        assert ids == [None, None]

    def test_no_sessions_dir(self, tmp_path):
        ids = get_codex_session_ids("/any", 2, home_override=tmp_path)
        assert ids == [None, None]

    def test_malformed_jsonl_skipped(self, fake_codex_sessions, tmp_path):
        fake_codex_sessions([
            ("/home/user/api", "uuid-good", 2000.0),
        ])
        # Add a malformed file
        bad_dir = tmp_path / ".codex" / "sessions" / "2026" / "06" / "30"
        bad_dir.mkdir(parents=True, exist_ok=True)
        bad_file = bad_dir / "bad.jsonl"
        bad_file.write_text("not json\n")
        os.utime(bad_file, (3000.0, 3000.0))

        ids = get_codex_session_ids(
            "/home/user/api", 2,
            home_override=tmp_path,
        )
        assert ids[0] == "uuid-good"
        assert ids[1] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_sessions.py::TestGetCodexSessionIds -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `sessions/codex.py`**

`src/multideck/sessions/codex.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path


def get_codex_session_ids(
    project_dir: str,
    count: int,
    home_override: Path | None = None,
) -> list[str | None]:
    home = home_override or Path.home()
    sess_root = home / ".codex" / "sessions"

    if not sess_root.is_dir():
        return [None] * count

    case_insensitive = sys.platform == "win32"
    compare_dir = project_dir.lower() if case_insensitive else project_dir

    files = sorted(
        sess_root.rglob("*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    ids: list[str | None] = []
    for f in files:
        if len(ids) >= count:
            break
        try:
            with open(f, encoding="utf-8") as fh:
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_sessions.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/multideck/sessions/codex.py tests/unit/test_sessions.py
git commit -m "feat: Codex session discovery — scan ~/.codex/sessions/ by CWD match"
```

---

### Task 6: Resume Command Construction

**Files:**
- Modify: `src/multideck/sessions/__init__.py`
- Create: `tests/unit/test_commands.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_commands.py`:

```python
from multideck.sessions import build_resume_command


class TestBuildResumeCommand:
    # Claude
    def test_claude_with_session(self):
        result = build_resume_command("claude", "claude --continue", "abc-123")
        assert result == "claude --resume abc-123"

    def test_claude_strips_continue(self):
        result = build_resume_command("claude", "claude --continue", "abc-123")
        assert "--continue" not in result

    def test_claude_strips_existing_resume(self):
        result = build_resume_command("claude", "claude --resume old-id", "new-id")
        assert result == "claude --resume new-id"
        assert "old-id" not in result

    def test_claude_no_session(self):
        result = build_resume_command("claude", "claude --continue", None)
        assert result == "claude"
        assert "--continue" not in result
        assert "--resume" not in result

    def test_claude_plain_command_with_session(self):
        result = build_resume_command("claude", "claude", "abc-123")
        assert result == "claude --resume abc-123"

    def test_claude_plain_command_no_session(self):
        result = build_resume_command("claude", "claude", None)
        assert result == "claude"

    # Codex
    def test_codex_with_session(self):
        result = build_resume_command("codex", "codex --yolo", "def-456")
        assert result == "codex resume def-456"

    def test_codex_no_session(self):
        result = build_resume_command("codex", "codex --yolo", None)
        assert result == "codex --yolo"

    def test_codex_plain_command_with_session(self):
        result = build_resume_command("codex", "codex", "def-456")
        assert result == "codex resume def-456"

    # Unknown tool
    def test_unknown_tool_returns_base_cmd(self):
        result = build_resume_command("mytool", "mytool --flag", "id-1")
        assert result == "mytool --flag"

    def test_unknown_tool_no_session(self):
        result = build_resume_command("mytool", "mytool --flag", None)
        assert result == "mytool --flag"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_commands.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `sessions/__init__.py`**

`src/multideck/sessions/__init__.py`:

```python
from __future__ import annotations

import re


def build_resume_command(tool: str, base_cmd: str, session_id: str | None) -> str:
    if tool == "claude":
        stripped = re.sub(r"--continue\s*", "", base_cmd)
        stripped = re.sub(r"--resume\s+\S+", "", stripped).strip()
        if session_id:
            return f"{stripped} --resume {session_id}"
        return stripped

    if tool == "codex":
        parts = base_cmd.split(None, 1)
        binary = parts[0]
        if session_id:
            return f"{binary} resume {session_id}"
        return base_cmd

    return base_cmd
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_commands.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/multideck/sessions/__init__.py tests/unit/test_commands.py
git commit -m "feat: resume command construction for claude and codex"
```

---

### Task 7: Title Generation

**Files:**
- Create: `src/multideck/titles.py`
- Create: `tests/unit/test_titles.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_titles.py`:

```python
from multideck.titles import generate_titles, get_leaf_name


class TestGetLeafName:
    def test_unix_path(self):
        assert get_leaf_name("/home/user/code/api") == "api"

    def test_windows_path(self):
        assert get_leaf_name("C:\\Users\\user\\code\\api") == "api"

    def test_forward_slashes(self):
        assert get_leaf_name("internal/api") == "api"

    def test_trailing_slash(self):
        assert get_leaf_name("/home/user/api/") == "api"

    def test_simple_name(self):
        assert get_leaf_name("api") == "api"


class TestGenerateTitles:
    def test_no_windows_uses_title(self):
        titles = generate_titles(title="my-api", path="internal/api", windows=None)
        assert titles == ["my-api"]

    def test_no_windows_no_title_uses_leaf(self):
        titles = generate_titles(title=None, path="internal/api", windows=None)
        assert titles == ["api"]

    def test_windows_int_auto_titles(self):
        titles = generate_titles(title=None, path="internal/api", windows=3)
        assert titles == ["api", "api-2", "api-3"]

    def test_windows_int_with_title(self):
        titles = generate_titles(title="my-api", path="internal/api", windows=3)
        assert titles == ["my-api", "my-api-2", "my-api-3"]

    def test_windows_1_same_as_none(self):
        titles = generate_titles(title=None, path="internal/api", windows=1)
        assert titles == ["api"]

    def test_windows_string_array(self):
        titles = generate_titles(title=None, path="internal/api", windows=["feat", "bugs", "review"])
        assert titles == ["feat", "bugs", "review"]

    def test_windows_string_array_ignores_title(self):
        titles = generate_titles(title="ignored", path="internal/api", windows=["a", "b"])
        assert titles == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_titles.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `titles.py`**

`src/multideck/titles.py`:

```python
from __future__ import annotations

import os


def get_leaf_name(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized


def generate_titles(
    title: str | None,
    path: str,
    windows: int | list[str] | None,
) -> list[str]:
    if isinstance(windows, list):
        return list(windows)

    base = title or get_leaf_name(path)
    count = windows if isinstance(windows, int) and windows > 1 else 1

    titles: list[str] = [base]
    for i in range(2, count + 1):
        titles.append(f"{base}-{i}")
    return titles
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_titles.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/multideck/titles.py tests/unit/test_titles.py
git commit -m "feat: title generation for single and multi-window projects"
```

---

### Task 8: Platform Interface + Detection

**Files:**
- Modify: `src/multideck/platform/__init__.py`

- [ ] **Step 1: Implement the platform ABC and data types**

`src/multideck/platform/__init__.py`:

```python
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from multideck.grid import Rect, MonitorRect


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
    ssh_host: str | None = None


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


def get_platform() -> Platform:
    if sys.platform == "win32":
        from multideck.platform.windows import WindowsPlatform
        return WindowsPlatform()
    elif sys.platform == "darwin":
        from multideck.platform.macos import MacOSPlatform
        return MacOSPlatform()
    else:
        from multideck.platform.linux import LinuxPlatform
        return LinuxPlatform()
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from multideck.platform import Platform, get_platform, TerminalLaunchOpts, VSCodeLaunchOpts; print('OK')"`
Expected: prints "OK" (actual platform impl will fail if the platform-specific module is missing — that's expected until Tasks 9-11).

- [ ] **Step 3: Commit**

```bash
git add src/multideck/platform/__init__.py
git commit -m "feat: platform ABC with detection and launch option dataclasses"
```

---

### Task 9: Windows Platform Implementation

**Files:**
- Create: `src/multideck/platform/windows.py`
- Create: `tests/platform/test_monitors.py`
- Create: `tests/platform/test_windows.py`

- [ ] **Step 1: Implement `platform/windows.py`**

`src/multideck/platform/windows.py`:

```python
from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess
from ctypes import POINTER, WINFUNCTYPE, byref, create_unicode_buffer, windll
from typing import Any

from multideck.grid import MonitorRect, Rect
from multideck.platform import Platform, TerminalLaunchOpts, VSCodeLaunchOpts

user32 = windll.user32
shcore = windll.shcore


class WindowsPlatform(Platform):
    def set_dpi_aware(self) -> None:
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

    def list_monitors(self) -> list[MonitorRect]:
        monitors: list[MonitorRect] = []

        MONITORINFOF_PRIMARY = 0x00000001

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szDevice", ctypes.c_wchar * 32),
            ]

        MONITORENUMPROC = WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
            POINTER(ctypes.wintypes.RECT), ctypes.c_void_p,
        )

        def callback(hmon, hdc, lprect, lparam):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            user32.GetMonitorInfoW(hmon, byref(info))
            wa = info.rcWork
            is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)

            scale = 1.0
            try:
                dpi_x = ctypes.c_uint()
                dpi_y = ctypes.c_uint()
                shcore.GetDpiForMonitor(hmon, 0, byref(dpi_x), byref(dpi_y))
                scale = dpi_x.value / 96.0
            except (OSError, AttributeError):
                pass

            monitors.append(MonitorRect(
                x=wa.left,
                y=wa.top,
                w=wa.right - wa.left,
                h=wa.bottom - wa.top,
                is_primary=is_primary,
                scale_factor=scale,
            ))
            return 1

        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
        return monitors

    def find_window(self, title: str, mode: str = "exact") -> int | None:
        result: int | None = None

        WNDENUMPROC = WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _):
            nonlocal result
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            text = buf.value
            if mode == "exact" and text == title:
                result = hwnd
                return False
            if mode == "contains" and title.lower() in text.lower():
                result = hwnd
                return False
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return result

    def move_window(self, handle: Any, rect: Rect) -> None:
        user32.MoveWindow(handle, rect.x, rect.y, rect.w, rect.h, True)
        user32.MoveWindow(handle, rect.x, rect.y, rect.w, rect.h, True)

    def launch_terminal(self, opts: TerminalLaunchOpts) -> None:
        args = [
            "wt", "-w", "new",
            "-d", opts.cwd,
            "--title", opts.title,
        ]
        if opts.color:
            args.extend(["--tabColor", opts.color])
        args.append("--suppressApplicationTitle")

        if opts.ssh_host:
            remote_dir = opts.ssh_remote_dir or opts.cwd
            inner = f"cd {remote_dir} && {opts.command}"
            if opts.ssh_shell:
                remote = f"{opts.ssh_shell} '{inner}'"
            else:
                remote = inner
            ssh_cmd = f'ssh -t {opts.ssh_host} "{remote}"'
            args.extend(["--", "cmd", "/k", ssh_cmd])
        else:
            args.extend(["--", "cmd", "/k", opts.command])

        subprocess.Popen(args)

    def launch_vscode(self, opts: VSCodeLaunchOpts) -> None:
        args = ["cmd", "/c", "code"]
        if opts.ssh_host:
            args.extend(["--remote", f"ssh-remote+{opts.ssh_host}"])
        args.append(opts.dir)
        subprocess.Popen(args)
```

- [ ] **Step 2: Write platform test for monitor enumeration**

`tests/platform/test_monitors.py`:

```python
import sys
import pytest

pytestmark = pytest.mark.platform


@pytest.fixture
def platform():
    from multideck.platform import get_platform
    return get_platform()


class TestListMonitors:
    def test_at_least_one_monitor(self, platform):
        monitors = platform.list_monitors()
        assert len(monitors) >= 1

    def test_monitor_has_positive_dimensions(self, platform):
        monitors = platform.list_monitors()
        for m in monitors:
            assert m.w > 0
            assert m.h > 0

    def test_monitor_has_scale_factor(self, platform):
        monitors = platform.list_monitors()
        for m in monitors:
            assert m.scale_factor >= 1.0

    def test_exactly_one_primary(self, platform):
        monitors = platform.list_monitors()
        primaries = [m for m in monitors if m.is_primary]
        assert len(primaries) == 1
```

- [ ] **Step 3: Write platform test for window finding**

`tests/platform/test_windows.py`:

```python
import subprocess
import sys
import time
import pytest

pytestmark = pytest.mark.platform


@pytest.fixture
def platform():
    from multideck.platform import get_platform
    return get_platform()


class TestFindWindow:
    @pytest.fixture
    def notepad_window(self):
        """Launch a window with a known title, yield, then kill it."""
        if sys.platform == "win32":
            proc = subprocess.Popen(["notepad.exe"])
            time.sleep(1)
            yield "Untitled - Notepad"
            proc.kill()
        elif sys.platform == "darwin":
            # AppleScript to open a TextEdit window
            subprocess.run(["osascript", "-e", 'tell application "TextEdit" to make new document'], check=True)
            time.sleep(1)
            yield "Untitled"
            subprocess.run(["osascript", "-e", 'tell application "TextEdit" to quit'], check=False)
        else:
            proc = subprocess.Popen(["xterm", "-T", "test-multideck-find", "-e", "sleep 30"])
            time.sleep(1)
            yield "test-multideck-find"
            proc.kill()

    def test_find_existing_window(self, platform, notepad_window):
        handle = platform.find_window(notepad_window, mode="contains")
        assert handle is not None

    def test_find_nonexistent_window(self, platform):
        handle = platform.find_window("__nonexistent_window_title_99999__")
        assert handle is None
```

- [ ] **Step 4: Run platform tests (on Windows)**

Run: `pytest tests/platform/ -v -m platform`
Expected: PASS on Windows, skipped or FAIL on other platforms (they don't have implementations yet).

- [ ] **Step 5: Commit**

```bash
git add src/multideck/platform/windows.py tests/platform/
git commit -m "feat: Windows platform — ctypes Win32 for monitors, windows, terminals"
```

---

### Task 10: macOS Platform Implementation

**Files:**
- Create: `src/multideck/platform/macos.py`

- [ ] **Step 1: Implement `platform/macos.py`**

`src/multideck/platform/macos.py`:

```python
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from multideck.grid import MonitorRect, Rect
from multideck.platform import Platform, TerminalLaunchOpts, VSCodeLaunchOpts

SWIFT_MONITORS = """\
import AppKit
import Foundation
var monitors: [[String: Any]] = []
for (i, screen) in NSScreen.screens.enumerated() {
    let f = screen.frame
    let v = screen.visibleFrame
    monitors.append([
        "x": Int(v.origin.x), "y": Int(v.origin.y),
        "w": Int(v.size.width), "h": Int(v.size.height),
        "full_h": Int(f.size.height),
        "is_primary": i == 0,
        "scale": screen.backingScaleFactor,
    ])
}
let data = try! JSONSerialization.data(withJSONObject: monitors)
print(String(data: data, encoding: .utf8)!)
"""


class MacOSPlatform(Platform):
    def set_dpi_aware(self) -> None:
        pass  # macOS handles Retina automatically

    def list_monitors(self) -> list[MonitorRect]:
        result = subprocess.run(
            ["swift", "-e", SWIFT_MONITORS],
            capture_output=True, text=True, timeout=10,
        )
        raw = json.loads(result.stdout)
        monitors: list[MonitorRect] = []
        for m in raw:
            # macOS uses bottom-left origin; convert to top-left
            full_h = m["full_h"]
            y_top = full_h - m["y"] - m["h"]
            monitors.append(MonitorRect(
                x=m["x"],
                y=y_top if y_top >= 0 else m["y"],
                w=m["w"],
                h=m["h"],
                is_primary=m["is_primary"],
                scale_factor=m["scale"],
            ))
        return monitors

    def find_window(self, title: str, mode: str = "exact") -> dict | None:
        script = """
        tell application "System Events"
            set windowList to {}
            repeat with proc in (every process whose visible is true)
                repeat with w in (every window of proc)
                    set end of windowList to {procName:name of proc, winName:name of w}
                end repeat
            end repeat
        end tell
        return windowList
        """
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().split(", "):
            parts = line.split(":")
            if len(parts) < 2:
                continue
            win_name = parts[-1].strip()
            proc_name = parts[0].strip()
            if mode == "exact" and win_name == title:
                return {"process": proc_name, "window": win_name}
            if mode == "contains" and title.lower() in win_name.lower():
                return {"process": proc_name, "window": win_name}
        return None

    def move_window(self, handle: Any, rect: Rect) -> None:
        if not handle or "process" not in handle:
            return
        proc = handle["process"]
        win = handle["window"]
        script = f"""
        tell application "System Events"
            tell process "{proc}"
                set position of window "{win}" to {{{rect.x}, {rect.y}}}
                set size of window "{win}" to {{{rect.w}, {rect.h}}}
            end tell
        end tell
        """
        subprocess.run(["osascript", "-e", script], timeout=10)

    def launch_terminal(self, opts: TerminalLaunchOpts) -> None:
        if opts.ssh_host:
            remote_dir = opts.ssh_remote_dir or opts.cwd
            inner = f"cd {remote_dir} && {opts.command}"
            if opts.ssh_shell:
                cmd = f"ssh -t {opts.ssh_host} \"{opts.ssh_shell} '{inner}'\""
            else:
                cmd = f"ssh -t {opts.ssh_host} \"{inner}\""
        else:
            cmd = f"cd {opts.cwd} && {opts.command}"

        # Try terminal emulators in priority order
        if shutil.which("kitty"):
            args = ["kitty", "--title", opts.title, "--directory", opts.cwd, "sh", "-c", cmd]
            subprocess.Popen(args)
        elif self._has_app("iTerm"):
            script = f"""
            tell application "iTerm"
                create window with default profile command "cd {opts.cwd} && {cmd}"
                tell current session of current window
                    set name to "{opts.title}"
                end tell
            end tell
            """
            subprocess.Popen(["osascript", "-e", script])
        else:
            script = f"""
            tell application "Terminal"
                do script "cd {opts.cwd} && {cmd}"
                set custom title of front window to "{opts.title}"
            end tell
            """
            subprocess.Popen(["osascript", "-e", script])

    def launch_vscode(self, opts: VSCodeLaunchOpts) -> None:
        args = ["code"]
        if opts.ssh_host:
            args.extend(["--remote", f"ssh-remote+{opts.ssh_host}"])
        args.append(opts.dir)
        subprocess.Popen(args)

    @staticmethod
    def _has_app(name: str) -> bool:
        result = subprocess.run(
            ["mdfind", f"kMDItemKind == 'Application' && kMDItemDisplayName == '{name}'"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(result.stdout.strip())
```

- [ ] **Step 2: Verify import on macOS**

Run: `python -c "from multideck.platform.macos import MacOSPlatform; print('OK')"`
Expected: prints "OK" on any platform (no macOS-specific imports at module level).

- [ ] **Step 3: Commit**

```bash
git add src/multideck/platform/macos.py
git commit -m "feat: macOS platform — Swift for monitors, AppleScript for window ops"
```

---

### Task 11: Linux Platform Implementation

**Files:**
- Create: `src/multideck/platform/linux.py`

- [ ] **Step 1: Implement `platform/linux.py`**

`src/multideck/platform/linux.py`:

```python
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

from multideck.grid import MonitorRect, Rect
from multideck.platform import Platform, TerminalLaunchOpts, VSCodeLaunchOpts


class LinuxPlatform(Platform):
    def set_dpi_aware(self) -> None:
        pass  # DPI read from xrandr per-monitor; no global call needed

    def list_monitors(self) -> list[MonitorRect]:
        result = subprocess.run(
            ["xrandr", "--query"],
            capture_output=True, text=True, timeout=10,
        )
        monitors: list[MonitorRect] = []
        is_first = True
        for line in result.stdout.splitlines():
            match = re.match(
                r"^(\S+)\s+connected\s+(primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)",
                line,
            )
            if not match:
                continue
            name, primary, w, h, x, y = match.groups()
            w, h, x, y = int(w), int(h), int(x), int(y)

            # Compute scale from physical size if available
            scale = 1.0
            size_match = re.search(r"(\d+)mm x (\d+)mm", line)
            if size_match:
                phys_w_mm = int(size_match.group(1))
                if phys_w_mm > 0:
                    dpi = w / (phys_w_mm / 25.4)
                    scale = round(dpi / 96.0, 2)

            monitors.append(MonitorRect(
                x=x, y=y, w=w, h=h,
                is_primary=primary is not None or (is_first and not any(m.is_primary for m in monitors)),
                scale_factor=max(1.0, scale),
            ))
            is_first = False

        return monitors

    def find_window(self, title: str, mode: str = "exact") -> str | None:
        if mode == "exact" and shutil.which("xdotool"):
            result = subprocess.run(
                ["xdotool", "search", "--name", f"^{re.escape(title)}$"],
                capture_output=True, text=True, timeout=5,
            )
            wids = result.stdout.strip().splitlines()
            return wids[0] if wids else None

        if shutil.which("wmctrl"):
            result = subprocess.run(
                ["wmctrl", "-l"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                parts = line.split(None, 3)
                if len(parts) < 4:
                    continue
                wid, _, _, win_title = parts
                if mode == "exact" and win_title == title:
                    return wid
                if mode == "contains" and title.lower() in win_title.lower():
                    return wid

        return None

    def move_window(self, handle: Any, rect: Rect) -> None:
        if not handle:
            return
        if shutil.which("wmctrl"):
            subprocess.run(
                ["wmctrl", "-i", "-r", str(handle), "-e", f"0,{rect.x},{rect.y},{rect.w},{rect.h}"],
                timeout=5,
            )

    def launch_terminal(self, opts: TerminalLaunchOpts) -> None:
        if opts.ssh_host:
            remote_dir = opts.ssh_remote_dir or opts.cwd
            inner = f"cd {remote_dir} && {opts.command}"
            if opts.ssh_shell:
                cmd = f"ssh -t {opts.ssh_host} \"{opts.ssh_shell} '{inner}'\""
            else:
                cmd = f"ssh -t {opts.ssh_host} \"{inner}\""
        else:
            cmd = opts.command

        if shutil.which("kitty"):
            subprocess.Popen(["kitty", "--title", opts.title, "--directory", opts.cwd, "sh", "-c", cmd])
        elif shutil.which("alacritty"):
            subprocess.Popen(["alacritty", "--title", opts.title, "--working-directory", opts.cwd, "-e", "sh", "-c", cmd])
        elif shutil.which("gnome-terminal"):
            subprocess.Popen(["gnome-terminal", f"--title={opts.title}", f"--working-directory={opts.cwd}", "--", "sh", "-c", cmd])
        elif shutil.which("konsole"):
            subprocess.Popen(["konsole", "--title", opts.title, "--workdir", opts.cwd, "-e", "sh", "-c", cmd])
        elif shutil.which("xterm"):
            subprocess.Popen(["xterm", "-T", opts.title, "-e", f"cd {opts.cwd} && {cmd}"])
        else:
            raise RuntimeError("No supported terminal emulator found. Install one of: kitty, alacritty, gnome-terminal, konsole, xterm")

    def launch_vscode(self, opts: VSCodeLaunchOpts) -> None:
        args = ["code"]
        if opts.ssh_host:
            args.extend(["--remote", f"ssh-remote+{opts.ssh_host}"])
        args.append(opts.dir)
        subprocess.Popen(args)
```

- [ ] **Step 2: Verify import**

Run: `python -c "from multideck.platform.linux import LinuxPlatform; print('OK')"`
Expected: prints "OK"

- [ ] **Step 3: Commit**

```bash
git add src/multideck/platform/linux.py
git commit -m "feat: Linux platform — xrandr for monitors, xdotool/wmctrl for window ops"
```

---

### Task 12: Terminal Detection

**Files:**
- Create: `src/multideck/terminals.py`
- Create: `tests/platform/test_terminals.py`

- [ ] **Step 1: Write failing tests**

`tests/platform/test_terminals.py`:

```python
import sys
import pytest

pytestmark = pytest.mark.platform


class TestTerminalDetection:
    def test_detect_returns_string(self):
        from multideck.terminals import detect_terminal
        name = detect_terminal()
        assert isinstance(name, str)
        assert len(name) > 0

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_windows_uses_wt(self):
        from multideck.terminals import detect_terminal
        assert detect_terminal() == "wt"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
    def test_unix_finds_a_terminal(self):
        from multideck.terminals import detect_terminal
        name = detect_terminal()
        assert name in ("kitty", "alacritty", "gnome-terminal", "konsole", "xterm",
                         "iterm2", "warp", "terminal.app")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/platform/test_terminals.py -v -m platform`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `terminals.py`**

`src/multideck/terminals.py`:

```python
from __future__ import annotations

import functools
import shutil
import sys


UNIX_TERMINAL_PRIORITY = [
    "kitty",
    "alacritty",
    "gnome-terminal",
    "konsole",
    "xterm",
]

MACOS_TERMINAL_PRIORITY = [
    "kitty",
    # iTerm2 and Terminal.app checked via AppleScript, not shutil.which
]


@functools.cache
def detect_terminal() -> str:
    if sys.platform == "win32":
        return "wt"

    for name in UNIX_TERMINAL_PRIORITY:
        if shutil.which(name):
            return name

    if sys.platform == "darwin":
        return "terminal.app"

    raise RuntimeError(
        "No supported terminal emulator found. "
        "Install one of: kitty, alacritty, gnome-terminal, konsole, xterm"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/platform/test_terminals.py -v -m platform`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/multideck/terminals.py tests/platform/test_terminals.py
git commit -m "feat: terminal emulator detection with priority-ordered search"
```

---

### Task 13: Init Config (Folder Scanning)

**Files:**
- Create: `src/multideck/init_config.py`
- Modify: `tests/unit/test_config.py` (add init tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_config.py`:

```python
import os
from multideck.init_config import scan_for_projects, generate_config


class TestScanForProjects:
    def test_finds_git_repos(self, tmp_path):
        (tmp_path / "api" / ".git").mkdir(parents=True)
        (tmp_path / "web" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        paths = [r["path"] for r in repos]
        assert "api" in paths
        assert "web" in paths

    def test_finds_nested_repos(self, tmp_path):
        (tmp_path / "internal" / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        assert any(r["path"] == "internal/api" for r in repos)

    def test_adds_group_from_parent_folder(self, tmp_path):
        (tmp_path / "backend" / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        proj = [r for r in repos if r["path"] == "backend/api"][0]
        assert proj["group"] == "backend"

    def test_no_group_for_top_level(self, tmp_path):
        (tmp_path / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        proj = [r for r in repos if r["path"] == "api"][0]
        assert "group" not in proj

    def test_duplicate_leaf_gets_unique_title(self, tmp_path):
        (tmp_path / "frontend" / "api" / ".git").mkdir(parents=True)
        (tmp_path / "backend" / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        api_repos = [r for r in repos if r["path"].endswith("api")]
        titles = [r.get("title") for r in api_repos]
        assert all(t is not None for t in titles)
        assert len(set(titles)) == 2

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "node_modules" / "pkg" / ".git").mkdir(parents=True)
        (tmp_path / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        assert len(repos) == 1

    def test_fallback_to_subdirectories(self, tmp_path):
        (tmp_path / "api").mkdir()
        (tmp_path / "web").mkdir()
        repos = scan_for_projects(str(tmp_path))
        assert len(repos) == 2


class TestGenerateConfig:
    def test_generates_valid_config(self, tmp_path):
        (tmp_path / "api" / ".git").mkdir(parents=True)
        (tmp_path / "web" / ".git").mkdir(parents=True)
        config = generate_config(str(tmp_path))
        assert config["baseDir"] == str(tmp_path).replace("\\", "/")
        assert len(config["projects"]) == 2
        assert config["layout"]["columns"] == 2
        assert config["settings"]["defaultTool"] == "claude"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_config.py::TestScanForProjects -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `init_config.py`**

`src/multideck/init_config.py`:

```python
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".svn", ".hg", "bin", "obj",
    ".next", "dist", "vendor", ".venv", "target",
}

PALETTE = [
    "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ef4444", "#06b6d4",
    "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#6366f1", "#eab308",
]


def scan_for_projects(root: str, max_depth: int = 3) -> list[dict]:
    root_path = Path(root).resolve()
    repos: list[Path] = []
    stack: list[tuple[Path, int]] = [(root_path, 0)]

    while stack and len(repos) < 300:
        current, depth = stack.pop()
        if depth >= 1 and (current / ".git").is_dir():
            repos.append(current)
            continue
        if depth < max_depth:
            try:
                children = sorted(current.iterdir())
                for child in children:
                    if child.is_dir() and child.name not in SKIP_DIRS:
                        stack.append((child, depth + 1))
            except PermissionError:
                continue

    dirs = sorted(repos) if repos else sorted(
        d for d in root_path.iterdir()
        if d.is_dir() and d.name not in SKIP_DIRS
    )

    # Detect duplicate leaf names
    leaves = [d.name for d in dirs]
    leaf_counts = Counter(leaves)
    dup_leaves = {name for name, count in leaf_counts.items() if count > 1}

    projects: list[dict] = []
    for i, d in enumerate(dirs):
        rel = d.relative_to(root_path).as_posix()
        parts = rel.split("/")
        proj: dict = {"path": rel}
        if len(parts) > 1:
            proj["group"] = parts[0]
        if parts[-1] in dup_leaves:
            proj["title"] = rel.replace("/", "-")
        proj["color"] = PALETTE[i % len(PALETTE)]
        projects.append(proj)

    return projects


def generate_config(root: str) -> dict:
    projects = scan_for_projects(root)
    return {
        "baseDir": str(Path(root).resolve()).replace("\\", "/"),
        "layout": {"columns": 2, "rows": 1},
        "settings": {
            "defaultTool": "claude",
            "settleSeconds": 3,
            "launchDelayMs": 400,
            "tools": {
                "claude": "claude --continue",
                "codex": "codex",
            },
        },
        "projects": projects,
    }


def write_config(root: str, out_path: str, force: bool = False) -> bool:
    out = Path(out_path)
    if out.exists() and not force:
        return False
    config = generate_config(root)
    out.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_config.py::TestScanForProjects tests/unit/test_config.py::TestGenerateConfig -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/multideck/init_config.py tests/unit/test_config.py
git commit -m "feat: --init folder scanning with group detection and duplicate leaf handling"
```

---

### Task 14: CLI + Interactive Menu

**Files:**
- Create: `src/multideck/cli.py`
- Create: `tests/e2e/test_cli_flags.py`

- [ ] **Step 1: Implement `cli.py`**

`src/multideck/cli.py`:

```python
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
```

- [ ] **Step 2: Write CLI flag tests**

`tests/e2e/test_cli_flags.py`:

```python
import json
import subprocess
import sys
import pytest

pytestmark = pytest.mark.e2e


class TestCliFlags:
    def test_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "1.0.0" in result.stdout

    def test_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--go" in result.stdout
        assert "--retile-all" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--group" in result.stdout
        assert "--init" in result.stdout

    def test_no_config_exits_nonzero(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--config", str(tmp_path / "nope.json")],
            capture_output=True, text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode != 0
        assert "No config found" in result.stderr or "No config found" in result.stdout

    def test_invalid_json_exits_nonzero(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json{")
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--config", str(bad)],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_dry_run_no_launch(self, tmp_path):
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "projects": [{"path": str(tmp_path)}],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--dry-run", "--go", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_init_dry_run(self, tmp_path):
        (tmp_path / "proj" / ".git").mkdir(parents=True)
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--init", "--base-dir", str(tmp_path),
             "--dry-run", "--config", str(tmp_path / "out.json")],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "proj" in result.stdout

    def test_init_writes_config(self, tmp_path):
        (tmp_path / "proj" / ".git").mkdir(parents=True)
        out = tmp_path / "multideck.config.json"
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--init", "--base-dir", str(tmp_path),
             "--config", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert len(data["projects"]) == 1
```

- [ ] **Step 3: Run tests to verify pass/fail state**

Run: `pytest tests/e2e/test_cli_flags.py -v -m e2e`
Expected: `--version` and `--help` tests PASS (they don't need `launch.py`). Other tests may FAIL until Task 15 provides `launch.py`.

- [ ] **Step 4: Commit**

```bash
git add src/multideck/cli.py tests/e2e/test_cli_flags.py
git commit -m "feat: click CLI with --go, --init, --dry-run, --group, interactive menu"
```

---

### Task 15: Launch Orchestrator

**Files:**
- Create: `src/multideck/launch.py`
- Create: `tests/e2e/test_launch.py`
- Create: `tests/e2e/test_multi_window.py`
- Create: `tests/e2e/test_idempotency.py`
- Create: `tests/helpers/poll.py`

- [ ] **Step 1: Create the poll helper**

`tests/helpers/poll.py`:

```python
from __future__ import annotations

import time
from typing import Any, Callable


def poll_until(fn: Callable[[], Any], timeout: float = 10.0, interval: float = 0.5) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(interval)
    return None
```

- [ ] **Step 2: Implement `launch.py`**

`src/multideck/launch.py`:

```python
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import click

from multideck.config import MultideckConfig, ProjectConfig
from multideck.grid import compute_grid, Rect
from multideck.platform import Platform, TerminalLaunchOpts, VSCodeLaunchOpts, get_platform
from multideck.sessions import build_resume_command
from multideck.sessions.claude import encode_claude_project_path, get_claude_session_ids
from multideck.sessions.codex import get_codex_session_ids
from multideck.titles import generate_titles, get_leaf_name


@dataclass
class RunOpts:
    retile_all: bool = False
    dry_run: bool = False
    group: str | None = None
    config_path: str = ""


@dataclass
class _Target:
    name: str
    key: str
    mode: str  # "exact" or "contains"
    is_new: bool


def _resolve_path(raw: str, base_dir: str | None) -> str | None:
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if os.path.isabs(expanded):
        return expanded if os.path.isdir(expanded) else None
    if base_dir:
        joined = os.path.join(base_dir, expanded)
        return joined if os.path.isdir(joined) else None
    return None


def _get_session_ids(tool: str, project_dir: str, count: int) -> list[str | None]:
    if tool == "claude":
        return get_claude_session_ids(project_dir, count)
    if tool == "codex":
        return get_codex_session_ids(project_dir, count)
    return [None] * count


def run_multideck(config: MultideckConfig, opts: RunOpts) -> None:
    plat = get_platform()
    plat.set_dpi_aware()

    monitors = plat.list_monitors()
    if not monitors:
        click.echo("No monitors detected.", err=True)
        return

    slots = compute_grid(monitors, config.layout.columns, config.layout.rows)
    per_screen = config.layout.columns * config.layout.rows

    click.echo(
        f"Detected {len(monitors)} screen(s) -> {len(slots)} tile slot(s) "
        f"({config.layout.columns} x {config.layout.rows} per screen)"
    )
    if opts.dry_run:
        click.echo("DRY RUN — nothing will be launched or moved.\n")

    base_dir = config.base_dir
    if base_dir:
        base_dir = os.path.expandvars(os.path.expanduser(base_dir)).replace("/", os.sep)

    # Filter projects
    projects = [p for p in config.projects if p.enabled]
    if opts.group:
        projects = [p for p in projects if p.group and p.group.lower() == opts.group.lower()]
        if not projects:
            groups = sorted({p.group for p in config.projects if p.group})
            click.echo(f"No projects in group '{opts.group}'. Available: {', '.join(groups)}", err=True)
            return
        click.echo(f"Group '{opts.group}': {len(projects)} project(s)")

    # Check SSH availability
    has_remote = any(p.host for p in projects)
    if has_remote and not _cmd_exists("ssh"):
        click.echo("WARNING: remote projects configured but 'ssh' not on PATH.")

    targets: list[_Target] = []
    new_count = 0
    tools = config.settings.tools

    for proj in projects:
        tool = proj.tool or config.settings.default_tool
        is_remote = bool(proj.host)

        # VS Code projects
        if tool == "code":
            key = get_leaf_name(proj.remote_path or proj.path) if is_remote else get_leaf_name(proj.path)
            name = proj.title or key
            running = plat.find_window(key, mode="contains") is not None
            if not running and not opts.dry_run:
                vsc_dir = proj.remote_path or proj.path if is_remote else (_resolve_path(proj.path, base_dir) or proj.path)
                plat.launch_vscode(VSCodeLaunchOpts(
                    dir=vsc_dir,
                    ssh_host=proj.host if is_remote else None,
                ))
                time.sleep(config.settings.launch_delay_ms / 1000)
            if not running:
                new_count += 1
            targets.append(_Target(name=name, key=key, mode="contains", is_new=not running))
            _log_project(name, tool, running, proj.host)
            continue

        # Determine window count and titles
        windows_cfg = proj.windows
        if is_remote or tool == "code":
            windows_cfg = None
        titles = generate_titles(proj.title, proj.path, windows_cfg)
        window_count = len(titles)

        # Session discovery for multi-window
        session_ids: list[str | None] = [None] * window_count
        if window_count > 1 and tool in ("claude", "codex") and not is_remote:
            resolved_dir = _resolve_path(proj.path, base_dir)
            if resolved_dir:
                session_ids = _get_session_ids(tool, resolved_dir, window_count)

        base_cmd = tools.get(tool)
        if not base_cmd:
            click.echo(f"SKIP: {titles[0]} — unknown tool '{tool}' (add under settings.tools)")
            continue

        for i, win_title in enumerate(titles):
            # Build command (resume or as-is)
            if window_count > 1 and session_ids[i] is not None:
                cmd = build_resume_command(tool, base_cmd, session_ids[i])
            elif window_count > 1:
                cmd = build_resume_command(tool, base_cmd, None)
            else:
                cmd = base_cmd

            running = plat.find_window(win_title, mode="exact") is not None
            if not running and not opts.dry_run:
                if is_remote:
                    resolved_dir = proj.remote_path or proj.path
                    plat.launch_terminal(TerminalLaunchOpts(
                        title=win_title,
                        cwd=os.getcwd(),
                        command=cmd,
                        color=proj.color,
                        ssh_host=proj.host,
                        ssh_remote_dir=resolved_dir,
                        ssh_shell=config.settings.ssh.shell,
                    ))
                else:
                    resolved_dir = _resolve_path(proj.path, base_dir)
                    if not resolved_dir:
                        click.echo(f"SKIP: {proj.path} not found")
                        continue
                    plat.launch_terminal(TerminalLaunchOpts(
                        title=win_title,
                        cwd=resolved_dir,
                        command=cmd,
                        color=proj.color,
                    ))
                time.sleep(config.settings.launch_delay_ms / 1000)
            if not running:
                new_count += 1
            targets.append(_Target(name=win_title, key=win_title, mode="exact", is_new=not running))
            _log_project(win_title, tool, running, proj.host)

    # Tile
    to_place = targets if opts.retile_all else [t for t in targets if t.is_new]

    if not to_place:
        click.echo("\nNothing to position.")
        return

    label = " [retile all]" if opts.retile_all else (" [dry run]" if opts.dry_run else "")
    click.echo(f"\nTiling {len(to_place)} window(s){label}...")

    if not opts.dry_run and new_count > 0:
        time.sleep(config.settings.settle_seconds)

    for slot_idx, target in enumerate(to_place):
        pos = slots[slot_idx % len(slots)]
        screen_num = (slot_idx % len(slots)) // per_screen + 1

        if opts.dry_run:
            click.echo(f"  {target.name:<30} -> screen {screen_num} {pos.label}   {pos.w}x{pos.h} @ ({pos.x},{pos.y})")
            continue

        handle = plat.find_window(target.key, mode=target.mode)
        if handle is None and target.is_new:
            deadline = 20 if target.mode == "contains" else 6
            for _ in range(deadline):
                time.sleep(1)
                handle = plat.find_window(target.key, mode=target.mode)
                if handle is not None:
                    break

        if handle is not None:
            plat.move_window(handle, Rect(x=pos.x, y=pos.y, w=pos.w, h=pos.h))
            click.echo(f"  {target.name} -> screen {screen_num} {pos.label}")
        else:
            click.echo(f"  Not found: {target.name}")

    click.echo("\nDone!")


def _log_project(name: str, tool: str, running: bool, host: str | None) -> None:
    status = "OPEN:" if running else "NEW: "
    loc = f" @ {host}" if host else ""
    click.echo(f"{status} {name} [{tool}{loc}]")


def _cmd_exists(name: str) -> bool:
    import shutil
    return shutil.which(name) is not None
```

- [ ] **Step 3: Write basic launch e2e test**

`tests/e2e/test_launch.py`:

```python
import json
import subprocess
import sys
import pytest

pytestmark = pytest.mark.e2e


class TestLaunchDryRun:
    def test_two_projects_dry_run(self, tmp_path):
        (tmp_path / "api").mkdir()
        (tmp_path / "web").mkdir()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "baseDir": str(tmp_path),
            "projects": [
                {"path": "api"},
                {"path": "web"},
            ],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "api" in result.stdout
        assert "web" in result.stdout
        assert "Tiling" in result.stdout

    def test_group_filter_dry_run(self, tmp_path):
        (tmp_path / "api").mkdir()
        (tmp_path / "web").mkdir()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "baseDir": str(tmp_path),
            "projects": [
                {"path": "api", "group": "backend"},
                {"path": "web", "group": "frontend"},
            ],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "-g", "backend", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "api" in result.stdout

    def test_disabled_project_skipped(self, tmp_path):
        (tmp_path / "api").mkdir()
        (tmp_path / "skip").mkdir()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "baseDir": str(tmp_path),
            "projects": [
                {"path": "api"},
                {"path": "skip", "enabled": False},
            ],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "api" in result.stdout
        assert "skip" not in result.stdout.replace("skipped", "")

    def test_empty_projects(self, tmp_path):
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({"projects": []}))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Nothing to position" in result.stdout
```

- [ ] **Step 4: Write multi-window e2e test**

`tests/e2e/test_multi_window.py`:

```python
import json
import subprocess
import sys
import pytest

pytestmark = pytest.mark.e2e


class TestMultiWindowDryRun:
    def test_windows_int(self, tmp_path):
        (tmp_path / "api").mkdir()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "baseDir": str(tmp_path),
            "projects": [{"path": "api", "windows": 3}],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "api" in result.stdout
        assert "api-2" in result.stdout
        assert "api-3" in result.stdout
        assert "Tiling 3 window(s)" in result.stdout

    def test_windows_string_array(self, tmp_path):
        (tmp_path / "api").mkdir()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "baseDir": str(tmp_path),
            "projects": [{"path": "api", "windows": ["feat", "bugs"]}],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "feat" in result.stdout
        assert "bugs" in result.stdout

    def test_windows_ignored_for_code_tool(self, tmp_path):
        (tmp_path / "api").mkdir()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "baseDir": str(tmp_path),
            "projects": [{"path": "api", "tool": "code", "windows": 3}],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Only 1 window, not 3
        assert "Tiling 1 window(s)" in result.stdout
```

- [ ] **Step 5: Write idempotency placeholder test**

`tests/e2e/test_idempotency.py`:

```python
import json
import subprocess
import sys
import pytest

pytestmark = pytest.mark.e2e


class TestIdempotency:
    def test_dry_run_twice_same_output(self, tmp_path):
        (tmp_path / "api").mkdir()
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "baseDir": str(tmp_path),
            "projects": [{"path": "api"}],
        }))
        cmd = [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)]
        r1 = subprocess.run(cmd, capture_output=True, text=True)
        r2 = subprocess.run(cmd, capture_output=True, text=True)
        assert r1.returncode == 0
        assert r2.returncode == 0
        assert r1.stdout == r2.stdout
```

- [ ] **Step 6: Run all tests**

Run: `pytest tests/ -v --ignore=tests/platform --ignore=tests/e2e/test_ssh.py`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/multideck/launch.py tests/e2e/ tests/helpers/
git commit -m "feat: launch orchestrator with session discovery, multi-window, and tiling"
```

---

### Task 16: CI/CD Pipeline

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/actions/setup-virtual-displays/action.yml`
- Create: `.github/actions/setup-ssh-server/action.yml`
- Create: `.github/actions/install-terminals/action.yml`
- Create: `tests/e2e/test_ssh.py`

- [ ] **Step 1: Create the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  unit:
    strategy:
      fail-fast: false
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
      fail-fast: false
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
      fail-fast: false
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

- [ ] **Step 2: Create setup-virtual-displays action**

`.github/actions/setup-virtual-displays/action.yml`:

```yaml
name: Setup Virtual Displays
description: Create multi-monitor virtual display environments for CI

runs:
  using: composite
  steps:
    - name: Linux - Start Xvfb with virtual monitors
      if: runner.os == 'Linux'
      shell: bash
      run: |
        sudo apt-get update -q
        sudo apt-get install -yq xvfb xdotool wmctrl x11-xserver-utils
        Xvfb :99 -screen 0 5760x2160x24 &
        sleep 2
        export DISPLAY=:99
        # Create two virtual monitors: 1920x1080 at offset 0 and 1920x1080 at offset 1920
        # (different physical sizes to simulate different DPIs)
        xrandr --setmonitor VIRTUAL-1 1920/508x1080/286+0+0 none || true
        xrandr --setmonitor VIRTUAL-2 1920/340x1080/190+1920+0 none || true
        echo "DISPLAY=:99" >> "$GITHUB_ENV"

    - name: macOS - No virtual display needed
      if: runner.os == 'macOS'
      shell: bash
      run: echo "macOS CI runners have a virtual display by default"

    - name: Windows - No virtual display needed
      if: runner.os == 'Windows'
      shell: pwsh
      run: Write-Host "Windows CI runners have a virtual display by default"
```

- [ ] **Step 3: Create setup-ssh-server action**

`.github/actions/setup-ssh-server/action.yml`:

```yaml
name: Setup SSH Server
description: Start a local SSH server for e2e testing

runs:
  using: composite
  steps:
    - name: Linux - Setup OpenSSH
      if: runner.os == 'Linux'
      shell: bash
      run: |
        sudo apt-get install -yq openssh-server
        ssh-keygen -t ed25519 -f ~/.ssh/id_test -N ""
        cat ~/.ssh/id_test.pub >> ~/.ssh/authorized_keys
        chmod 600 ~/.ssh/authorized_keys
        sudo sed -i 's/#Port 22/Port 2222/' /etc/ssh/sshd_config
        sudo service ssh start
        echo "MULTIDECK_TEST_SSH_PORT=2222" >> "$GITHUB_ENV"
        echo "MULTIDECK_TEST_SSH_KEY=$HOME/.ssh/id_test" >> "$GITHUB_ENV"
        # Verify connection
        ssh -o StrictHostKeyChecking=no -i ~/.ssh/id_test -p 2222 localhost whoami

    - name: macOS - Setup OpenSSH
      if: runner.os == 'macOS'
      shell: bash
      run: |
        ssh-keygen -t ed25519 -f ~/.ssh/id_test -N ""
        cat ~/.ssh/id_test.pub >> ~/.ssh/authorized_keys
        chmod 600 ~/.ssh/authorized_keys
        sudo systemsetup -setremotelogin on
        echo "MULTIDECK_TEST_SSH_PORT=22" >> "$GITHUB_ENV"
        echo "MULTIDECK_TEST_SSH_KEY=$HOME/.ssh/id_test" >> "$GITHUB_ENV"
        ssh -o StrictHostKeyChecking=no -i ~/.ssh/id_test localhost whoami

    - name: Windows - Setup OpenSSH
      if: runner.os == 'Windows'
      shell: pwsh
      run: |
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
        Start-Service sshd
        Set-Service -Name sshd -StartupType Automatic
        ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\id_test" -N '""'
        $pub = Get-Content "$env:USERPROFILE\.ssh\id_test.pub"
        $authKeys = "$env:USERPROFILE\.ssh\authorized_keys"
        Add-Content -Path $authKeys -Value $pub
        echo "MULTIDECK_TEST_SSH_PORT=22" >> $env:GITHUB_ENV
        echo "MULTIDECK_TEST_SSH_KEY=$env:USERPROFILE\.ssh\id_test" >> $env:GITHUB_ENV
```

- [ ] **Step 4: Create install-terminals action**

`.github/actions/install-terminals/action.yml`:

```yaml
name: Install Terminal Emulators
description: Install terminal emulators for platform and e2e tests

runs:
  using: composite
  steps:
    - name: Linux - Install terminals
      if: runner.os == 'Linux'
      shell: bash
      run: |
        sudo apt-get install -yq xterm
        # gnome-terminal and kitty are heavier; xterm is sufficient for CI

    - name: macOS - Terminal.app is built-in
      if: runner.os == 'macOS'
      shell: bash
      run: echo "Terminal.app available by default"

    - name: Windows - Windows Terminal is pre-installed
      if: runner.os == 'Windows'
      shell: pwsh
      run: Write-Host "Windows Terminal available by default on GitHub runners"
```

- [ ] **Step 5: Write SSH e2e test**

`tests/e2e/test_ssh.py`:

```python
import json
import os
import subprocess
import sys
import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture
def ssh_available():
    port = os.environ.get("MULTIDECK_TEST_SSH_PORT")
    key = os.environ.get("MULTIDECK_TEST_SSH_KEY")
    if not port or not key:
        pytest.skip("SSH test server not configured (set MULTIDECK_TEST_SSH_PORT and MULTIDECK_TEST_SSH_KEY)")
    return {"port": port, "key": key}


class TestSSHLaunch:
    def test_ssh_project_dry_run(self, tmp_path, ssh_available):
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "projects": [{
                "host": f"localhost",
                "path": "/tmp",
                "tool": "claude",
                "title": "remote-test",
            }],
            "settings": {
                "tools": {"claude": "echo hello"},
                "ssh": {"shell": "bash -lc"},
            },
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "remote-test" in result.stdout

    def test_ssh_missing_warning(self, tmp_path, monkeypatch):
        # Temporarily hide ssh from PATH
        monkeypatch.setenv("PATH", str(tmp_path))
        cfg = tmp_path / "multideck.config.json"
        cfg.write_text(json.dumps({
            "projects": [{"host": "fake@host", "path": "/tmp"}],
        }))
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--dry-run", "--config", str(cfg)],
            capture_output=True, text=True,
            env={**os.environ, "PATH": str(tmp_path)},
        )
        # Should still run (dry run) but may warn about SSH
        assert result.returncode == 0
```

- [ ] **Step 6: Create virtual_display and ssh_server test helpers**

`tests/helpers/virtual_display.py`:

```python
"""Helpers for setting up virtual displays in CI.

These are used by the GitHub Actions setup scripts. The Python helpers
here are for tests that need to programmatically check display state.
"""
from __future__ import annotations

import os
import subprocess
import sys


def get_display() -> str | None:
    if sys.platform == "win32":
        return "windows"
    return os.environ.get("DISPLAY")


def has_display() -> bool:
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        return True
    return get_display() is not None
```

`tests/helpers/ssh_server.py`:

```python
"""Helpers for SSH server test configuration."""
from __future__ import annotations

import os


def get_ssh_config() -> dict | None:
    port = os.environ.get("MULTIDECK_TEST_SSH_PORT")
    key = os.environ.get("MULTIDECK_TEST_SSH_KEY")
    if not port or not key:
        return None
    return {"port": int(port), "key": key, "host": "localhost"}
```

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: all unit tests PASS

Run: `pytest tests/ -v --ignore=tests/platform --ignore=tests/e2e/test_ssh.py -m "not platform"`
Expected: all runnable tests PASS

- [ ] **Step 8: Commit**

```bash
git add .github/ tests/e2e/test_ssh.py tests/helpers/
git commit -m "ci: GitHub Actions matrix with virtual displays, SSH servers, and terminal setup"
```

---

### Task 17: Final Integration + Packaging Verification

**Files:**
- Verify: all modules import correctly
- Verify: `python -m build` produces wheel
- Verify: installed CLI works

- [ ] **Step 1: Verify all imports**

Run:
```bash
python -c "
from multideck.config import load_config, MultideckConfig
from multideck.grid import compute_grid, MonitorRect, TileSlot
from multideck.sessions.claude import get_claude_session_ids, encode_claude_project_path
from multideck.sessions.codex import get_codex_session_ids
from multideck.sessions import build_resume_command
from multideck.titles import generate_titles, get_leaf_name
from multideck.init_config import scan_for_projects, generate_config, write_config
from multideck.platform import Platform, get_platform, TerminalLaunchOpts, VSCodeLaunchOpts
from multideck.launch import run_multideck, RunOpts
from multideck.cli import main
print('All imports OK')
"
```
Expected: prints "All imports OK"

- [ ] **Step 2: Build wheel**

Run:
```bash
pip install build
python -m build
```
Expected: produces `dist/multideck-1.0.0-py3-none-any.whl` and `dist/multideck-1.0.0.tar.gz`

- [ ] **Step 3: Install from wheel and verify CLI**

Run:
```bash
pip install dist/multideck-1.0.0-py3-none-any.whl
multideck --version
multideck --help
```
Expected: `--version` prints `1.0.0`, `--help` shows all flags

- [ ] **Step 4: Run complete test suite**

Run: `pytest tests/unit/ tests/e2e/test_cli_flags.py tests/e2e/test_launch.py tests/e2e/test_multi_window.py tests/e2e/test_idempotency.py -v`
Expected: all tests PASS

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: verify packaging, imports, and full test suite"
```

---

## Spec Coverage Matrix

| Spec Section | Task(s) |
|---|---|
| 2. Project Structure | 1 |
| 3. Config Schema | 2 |
| 4.1 Claude Session Discovery | 4 |
| 4.2 Codex Session Discovery | 5 |
| 4.3 Resume Command Construction | 6 |
| 5. Platform Interface | 8 |
| 5.1 Windows Platform | 9 |
| 5.2 macOS Platform | 10 |
| 5.3 Linux Platform | 11 |
| 5.4 Terminal Detection | 12 |
| 6. Grid Computation | 3 |
| 7. Launch Orchestrator | 15 |
| 8. CLI | 14 |
| 9. PyPI Packaging | 1, 17 |
| 10. CI/CD Pipeline | 16 |
| 11. Migration | 14 (same flags) |
| Title generation | 7 |
| --init folder scanning | 13 |
