"""Typed, validated config — the schema half of multideck's two-path config contract.

This module owns the *typed* view of a config file: the dataclasses
(``LayoutConfig``, ``Settings``, ``ProjectConfig``, ``MultideckConfig`` …),
``SCHEMA_VERSION``, ``DEFAULT_TOOLS``, and the pure ``load_config`` that parses,
validates, and warns but never writes to disk. ``default_config`` /
``settings_to_dict`` are the one envelope factory every config generator shares,
and ``migrate_config_file`` is this module's only writer. The other half of the
contract — raw-dict round-tripping that preserves unknown/unmodeled keys for the
interactive editor — lives in ``cli/config_io.py``; the two paths never overlap.
"""

from __future__ import annotations

import colorsys
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from collections.abc import Callable

SCHEMA_VERSION = 2

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
class AttentionSettings:
    """Which attention renderers the daemon runs (see multideck.attention).

    toast/ntfy default off: toast needs the optional winotify extra and ntfy
    needs a MULTIDECK_NTFY_TOPIC env var — off-by-default keeps a fresh
    config from warning about capabilities that aren't wired yet."""

    badge: bool = True
    flash: bool = True
    toast: bool = False
    ntfy: bool = False


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
    attention: AttentionSettings = field(default_factory=AttentionSettings)
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


# --- typed JSON-object accessors -------------------------------------------
# json.loads yields an untyped object graph; these narrow a raw
# ``dict[str, object]`` value to the concrete type each Settings/Project field
# expects, falling back to the default when the JSON type is wrong. This is the
# "object + isinstance narrowing" boundary (audit §6.4) -- no ``Any``, no
# ``cast`` -- and it makes a mistyped field degrade to its default instead of
# crashing deep in the launch path.


def _load_json_object(text: str) -> dict[str, object]:
    """Parse ``text`` as a JSON object, or raise ConfigError. The single JSON
    entry point shared by load_config and migrate_config_file."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError("Config must be a JSON object")
    return data


def _obj(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key)
    return value if isinstance(value, dict) else {}  # ty: ignore[invalid-return-type]  # reason: isinstance narrows; ty 0.0.56 invariance gap


def _str(raw: dict[str, object], key: str, default: str) -> str:
    value = raw.get(key, default)
    return value if isinstance(value, str) else default


def _str_or_none(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) else None


def _int(raw: dict[str, object], key: str, default: int) -> int:
    value = raw.get(key, default)
    # bool is an int subclass; a JSON boolean is not a valid integer field.
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _bool(raw: dict[str, object], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    return value if isinstance(value, bool) else default


def _bool_or_none(raw: dict[str, object], key: str) -> bool | None:
    value = raw.get(key)
    return value if isinstance(value, bool) else None


def _tools(raw: dict[str, object], default: dict[str, str]) -> dict[str, str]:
    value = raw.get("tools")
    if not isinstance(value, dict):
        return dict(default)
    return {str(k): v for k, v in value.items() if isinstance(v, str)}


def _windows(raw: dict[str, object]) -> int | list[str] | None:
    value = raw.get("windows")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return None


def _parse_ssh(raw: dict[str, object]) -> SSHConfig:
    return SSHConfig(shell=_str(raw, "shell", "bash -lc"))


def _parse_attention(raw: dict[str, object]) -> AttentionSettings:
    return AttentionSettings(
        badge=_bool(raw, "badge", True),
        flash=_bool(raw, "flash", True),
        toast=_bool(raw, "toast", False),
        ntfy=_bool(raw, "ntfy", False),
    )


def _parse_settings(raw: dict[str, object] | None) -> Settings:
    if not raw:
        return Settings()
    return Settings(
        default_tool=_str(raw, "defaultTool", "claude"),
        settle_seconds=_int(raw, "settleSeconds", 3),
        launch_delay_ms=_int(raw, "launchDelayMs", 400),
        happy=_bool(raw, "happy", False),
        psmux=_bool(raw, "psmux", False),
        upload_server=_bool(raw, "uploadServer", False),
        upload_port=_int(raw, "uploadPort", 8033),
        ssh=_parse_ssh(_obj(raw, "ssh")),
        attention=_parse_attention(_obj(raw, "attention")),
        tools=_tools(raw, DEFAULT_TOOLS),
    )


def layout_to_dict(layout: LayoutConfig) -> dict[str, int]:
    return {"columns": layout.columns, "rows": layout.rows}


def settings_to_dict(settings: Settings) -> dict[str, object]:
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
        "attention": {
            "badge": settings.attention.badge,
            "flash": settings.attention.flash,
            "toast": settings.attention.toast,
            "ntfy": settings.attention.ntfy,
        },
        "tools": dict(settings.tools),
    }


def default_config(
    projects: list[dict[str, object]], base_dir: str | None = None
) -> dict[str, object]:
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


def _parse_project(raw: dict[str, object]) -> ProjectConfig:
    if "path" not in raw:
        raise ConfigError("Each project must have a 'path' field")
    return ProjectConfig(
        path=_str(raw, "path", ""),
        group=_str_or_none(raw, "group"),
        color=_str_or_none(raw, "color"),
        tool=_str_or_none(raw, "tool"),
        title=_str_or_none(raw, "title"),
        enabled=_bool(raw, "enabled", True),
        happy=_bool_or_none(raw, "happy"),
        host=_str_or_none(raw, "host"),
        remote_path=_str_or_none(raw, "remotePath"),
        windows=_windows(raw),
    )


def _random_tab_color(used: set[str]) -> str:
    for _ in range(200):
        h = random.random()
        s = random.uniform(0.55, 0.95)
        light = random.uniform(0.40, 0.65)
        r, g, b = colorsys.hls_to_rgb(h, light, s)
        color = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
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


_TYPE_LABELS: dict[type, str] = {
    int: "an integer",
    str: "a string",
    bool: "a boolean",
    float: "a number",
    dict: "an object",
    list: "an array",
}


def _describe_type(t: type) -> str:
    return _TYPE_LABELS.get(t, t.__name__)


def _require_type(
    raw: dict[str, object], key: str, types: type | tuple[type, ...], label: str
) -> None:
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
    "defaultTool",
    "settleSeconds",
    "launchDelayMs",
    "happy",
    "psmux",
    "uploadServer",
    "uploadPort",
    "ssh",
    "attention",
    "tools",
}
_ALLOWED_SSH_KEYS = {"shell"}
_ALLOWED_ATTENTION_KEYS = {"badge", "flash", "toast", "ntfy"}
_ALLOWED_PROJECT_KEYS = {
    "path",
    "group",
    "color",
    "tool",
    "title",
    "enabled",
    "happy",
    "host",
    "remotePath",
    "windows",
}


def _warn_unknown_keys(raw: dict[str, object], allowed: set[str], path: str) -> None:
    for key in sorted(set(raw) - allowed):
        field_path = f"{path}.{key}" if path else key
        click.echo(f"Warning: unknown config key: {field_path}", err=True)


def _parse_layout(raw: dict[str, object]) -> LayoutConfig:
    layout_raw = _obj(raw, "layout")
    _warn_unknown_keys(layout_raw, _ALLOWED_LAYOUT_KEYS, "layout")
    _require_type(layout_raw, "columns", int, "layout.columns")
    _require_type(layout_raw, "rows", int, "layout.rows")
    return LayoutConfig(
        columns=max(1, _int(layout_raw, "columns", 2)),
        rows=max(1, _int(layout_raw, "rows", 1)),
    )


def load_config(path: str) -> MultideckConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = _load_json_object(config_path.read_text(encoding="utf-8"))

    projects_raw = raw.get("projects")
    if not isinstance(projects_raw, list):
        raise ConfigError("Config must have a 'projects' array")

    _require_type(raw, "version", int, "version")
    version = _int(raw, "version", 0)
    if version < SCHEMA_VERSION:
        click.echo(
            f"Warning: config schema v{version} < v{SCHEMA_VERSION}; run: multideck config migrate",
            err=True,
        )
    _warn_unknown_keys(raw, _ALLOWED_TOP_KEYS, "")

    layout = _parse_layout(raw)

    settings_raw = _obj(raw, "settings")
    _warn_unknown_keys(settings_raw, _ALLOWED_SETTINGS_KEYS, "settings")
    _warn_unknown_keys(_obj(settings_raw, "ssh"), _ALLOWED_SSH_KEYS, "settings.ssh")
    _warn_unknown_keys(
        _obj(settings_raw, "attention"), _ALLOWED_ATTENTION_KEYS, "settings.attention"
    )

    projects: list[ProjectConfig] = []
    for i, p in enumerate(projects_raw):
        p_obj = p if isinstance(p, dict) else {}
        _warn_unknown_keys(p_obj, _ALLOWED_PROJECT_KEYS, f"projects[{i}]")  # ty: ignore[invalid-argument-type]  # reason: isinstance guard; ty 0.0.56 invariance gap
        projects.append(_parse_project(p_obj))  # ty: ignore[invalid-argument-type]  # reason: isinstance guard; ty 0.0.56 invariance gap
    _backfill_colors(projects)

    return MultideckConfig(
        projects=projects,
        base_dir=_str_or_none(raw, "baseDir"),
        layout=layout,
        settings=_parse_settings(settings_raw),
        version=version,
    )


def _migrate_0_to_1(raw: dict[str, object]) -> dict[str, object]:
    raw = dict(raw)
    raw["version"] = 1
    return raw


def _migrate_1_to_2(raw: dict[str, object]) -> dict[str, object]:
    """v2 adds settings.attention — absent keys parse to their defaults, so
    the migration only stamps the version and materializes the section so
    hand-editors can see the knobs exist."""
    raw = dict(raw)
    settings = raw.get("settings")
    if isinstance(settings, dict) and "attention" not in settings:
        settings["attention"] = {  # ty: ignore[invalid-assignment]  # reason: isinstance guard; ty 0.0.56 invariance gap
            "badge": True,
            "flash": True,
            "toast": False,
            "ntfy": False,
        }
    raw["version"] = 2
    return raw


_MIGRATIONS: dict[int, Callable[[dict[str, object]], dict[str, object]]] = {
    0: _migrate_0_to_1,
    1: _migrate_1_to_2,
}


def migrate_raw(raw: dict[str, object]) -> dict[str, object]:
    """Apply pending schema migrations to a raw config dict, returning the
    migrated dict. Pure -- does not touch disk; migrate_config_file does."""
    version = _int(raw, "version", 0)
    while version < SCHEMA_VERSION:
        raw = _MIGRATIONS[version](raw)
        version = _int(raw, "version", 0)
    return raw


def migrate_config_file(path: str) -> bool:
    """Read, migrate to SCHEMA_VERSION, and persist backfilled project
    colors, writing the canonical JSON shape back to `path`. Returns True if
    the file changed, False if it was already current. This is the one place
    in config.py that writes to disk -- load_config stays pure (R10)."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = _load_json_object(config_path.read_text(encoding="utf-8"))

    original_version = _int(raw, "version", 0)
    raw = migrate_raw(raw)
    version_changed = _int(raw, "version", 0) != original_version

    projects_raw = raw.get("projects")
    projects_list = projects_raw if isinstance(projects_raw, list) else []
    projects = [_parse_project(p if isinstance(p, dict) else {}) for p in projects_list]  # ty: ignore[invalid-argument-type]  # reason: isinstance guard; ty 0.0.56 invariance gap
    colors_changed = _backfill_colors(projects)
    for i, p in enumerate(projects):
        entry = projects_list[i]
        if isinstance(entry, dict):
            entry["color"] = p.color  # ty: ignore[invalid-assignment]  # reason: isinstance guard; ty 0.0.56 invariance gap

    if not version_changed and not colors_changed:
        return False

    config_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return True
