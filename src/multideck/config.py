from __future__ import annotations

import colorsys
import json
import random
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
    happy: bool = False
    psmux: bool = False
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
        happy=raw.get("happy"),
        host=raw.get("host"),
        remote_path=raw.get("remotePath"),
        windows=raw.get("windows"),
    )


def _random_tab_color(used: set[str]) -> str:
    for _ in range(200):
        h = random.random()
        s = random.uniform(0.55, 0.95)
        l = random.uniform(0.40, 0.65)
        r, g, b = colorsys.hls_to_rgb(h, l, s)
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

    projects = [_parse_project(p) for p in raw["projects"]]
    if _backfill_colors(projects):
        for i, p in enumerate(projects):
            raw["projects"][i].setdefault("color", p.color)
        config_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    return MultideckConfig(
        projects=projects,
        base_dir=raw.get("baseDir"),
        layout=layout,
        settings=_parse_settings(raw.get("settings")),
    )
