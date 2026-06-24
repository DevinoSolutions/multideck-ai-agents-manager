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
        "cursor-agent": "cursor-agent",
        "agy": "agy",
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
        tools=raw.get("tools", {
            "claude": "claude --continue",
            "codex": "codex",
            "cursor-agent": "cursor-agent",
            "agy": "agy",
        }),
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
