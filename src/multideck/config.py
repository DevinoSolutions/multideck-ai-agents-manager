from __future__ import annotations

import colorsys
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

DEFAULT_TOOLS: dict[str, str] = {
    "claude": "claude --continue",
    "codex": "codex",
    "cursor-agent": "cursor-agent",
    "agy": "agy",
}


class ConfigError(ValueError):
    """Structurally invalid multideck config: bad JSON, wrong-typed field, or missing required key."""


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
    happy: bool = False
    psmux: bool = False
    upload_server: bool = False
    upload_port: int = 8033
    ssh: SSHConfig = field(default_factory=SSHConfig)
    tools: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TOOLS))


@dataclass
class ProjectConfig:
    path: str
    group: str | None = None
    color: str | None = None
    tool: str | None = None
    title: str | None = None
    enabled: bool = True
    happy: bool | None = None
    host: str | None = None
    remote_path: str | None = None
    windows: int | list[str] | None = None


@dataclass
class MultideckConfig:
    projects: list[ProjectConfig]
    base_dir: str | None = None
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    settings: Settings = field(default_factory=Settings)
    version: int = SCHEMA_VERSION


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
        happy=raw.get("happy", False),
        psmux=raw.get("psmux", False),
        upload_server=raw.get("uploadServer", False),
        upload_port=raw.get("uploadPort", 8033),
        ssh=_parse_ssh(raw.get("ssh")),
        tools=raw.get("tools", dict(DEFAULT_TOOLS)),
    )


def layout_to_dict(layout: LayoutConfig) -> dict:
    return {"columns": layout.columns, "rows": layout.rows}


def settings_to_dict(settings: Settings) -> dict:
    """Inverse of _parse_settings -- the single serializer every config
    generator (init_config, discover) delegates to via default_config, so
    the emitted envelope can never drift from what the loader parses (R9)."""
    return {
        "defaultTool": settings.default_tool,
        "settleSeconds": settings.settle_seconds,
        "launchDelayMs": settings.launch_delay_ms,
        "happy": settings.happy,
        "psmux": settings.psmux,
        "uploadServer": settings.upload_server,
        "uploadPort": settings.upload_port,
        "ssh": {"shell": settings.ssh.shell},
        "tools": dict(settings.tools),
    }


def default_config(projects: list[dict], base_dir: str | None = None) -> dict:
    """The one envelope factory. init_config.generate_config and
    discover.projects_to_config both delegate here for version/layout/
    settings so the three generators can't hand-build divergent defaults."""
    return {
        "version": SCHEMA_VERSION,
        "baseDir": (base_dir or "").replace("\\", "/"),
        "layout": layout_to_dict(LayoutConfig()),
        "settings": settings_to_dict(Settings()),
        "projects": projects,
    }


def _parse_project(raw: dict) -> ProjectConfig:
    if "path" not in raw:
        raise ConfigError("Each project must have a 'path' field")
    return ProjectConfig(
        path=raw["path"],
        group=raw.get("group"),
        color=raw.get("color"),
        tool=raw.get("tool"),
        title=raw.get("title"),
        enabled=raw.get("enabled", True),
        happy=raw.get("happy"),
        host=raw.get("host"),
        remote_path=raw.get("remotePath"),
        windows=raw.get("windows"),
    )


def _random_tab_color(used: set[str]) -> str:
    for _ in range(200):
        h = random.random()
        s = random.uniform(0.55, 0.95)
        light = random.uniform(0.40, 0.65)
        r, g, b = colorsys.hls_to_rgb(h, light, s)
        color = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        if color not in used:
            return color
    return f"#{random.randint(0, 0xFFFFFF):06x}"


def _backfill_colors(projects: list[ProjectConfig]) -> bool:
    used = {p.color for p in projects if p.color}
    changed = False
    for p in projects:
        if not p.color:
            p.color = _random_tab_color(used)
            used.add(p.color)
            changed = True
    return changed


_TYPE_LABELS = {
    int: "an integer", str: "a string", bool: "a boolean",
    float: "a number", dict: "an object", list: "an array",
}


def _describe_type(t: type) -> str:
    return _TYPE_LABELS.get(t, t.__name__)


def _require_type(raw: dict, key: str, types: type | tuple[type, ...], label: str) -> None:
    """Raise ConfigError if raw[key] is present but not an instance of `types`.

    bool is rejected for int-only fields (bool is an int subclass in Python)
    unless bool is explicitly included in `types`.
    """
    if key not in raw:
        return
    value = raw[key]
    allowed = types if isinstance(types, tuple) else (types,)
    if isinstance(value, bool) and bool not in allowed and int in allowed:
        wrong_type = True
    else:
        wrong_type = not isinstance(value, allowed)
    if wrong_type:
        expected = " or ".join(_describe_type(t) for t in allowed)
        raise ConfigError(f"{label} must be {expected}, got {type(value).__name__}")


_ALLOWED_TOP_KEYS = {"version", "baseDir", "layout", "settings", "projects"}
_ALLOWED_LAYOUT_KEYS = {"columns", "rows"}
_ALLOWED_SETTINGS_KEYS = {
    "defaultTool", "settleSeconds", "launchDelayMs", "happy", "psmux",
    "uploadServer", "uploadPort", "ssh", "tools",
}
_ALLOWED_SSH_KEYS = {"shell"}
_ALLOWED_PROJECT_KEYS = {
    "path", "group", "color", "tool", "title", "enabled", "happy",
    "host", "remotePath", "windows",
}


def _warn_unknown_keys(raw: dict, allowed: set[str], path: str) -> None:
    for key in sorted(set(raw) - allowed):
        field_path = f"{path}.{key}" if path else key
        print(f"Warning: unknown config key: {field_path}", file=sys.stderr)


def _parse_layout(raw: dict) -> LayoutConfig:
    layout_raw = raw.get("layout", {})
    _warn_unknown_keys(layout_raw, _ALLOWED_LAYOUT_KEYS, "layout")
    _require_type(layout_raw, "columns", int, "layout.columns")
    _require_type(layout_raw, "rows", int, "layout.rows")
    return LayoutConfig(
        columns=max(1, layout_raw.get("columns", 2)),
        rows=max(1, layout_raw.get("rows", 1)),
    )


def load_config(path: str) -> MultideckConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    text = config_path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config is not valid JSON: {e}") from e

    if "projects" not in raw or not isinstance(raw["projects"], list):
        raise ConfigError("Config must have a 'projects' array")

    _require_type(raw, "version", int, "version")
    version = raw.get("version", 0)
    if version < SCHEMA_VERSION:
        print(
            f"Warning: config schema v{version} < v{SCHEMA_VERSION}; run: multideck config migrate",
            file=sys.stderr,
        )
    _warn_unknown_keys(raw, _ALLOWED_TOP_KEYS, "")

    layout = _parse_layout(raw)

    settings_raw = raw.get("settings") or {}
    _warn_unknown_keys(settings_raw, _ALLOWED_SETTINGS_KEYS, "settings")
    _warn_unknown_keys(settings_raw.get("ssh") or {}, _ALLOWED_SSH_KEYS, "settings.ssh")

    for i, p in enumerate(raw["projects"]):
        _warn_unknown_keys(p, _ALLOWED_PROJECT_KEYS, f"projects[{i}]")

    projects = [_parse_project(p) for p in raw["projects"]]
    _backfill_colors(projects)

    return MultideckConfig(
        projects=projects,
        base_dir=raw.get("baseDir"),
        layout=layout,
        settings=_parse_settings(settings_raw),
        version=version,
    )
