from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path


def _decode_claude_dir_name(encoded: str) -> str | None:
    """Try to reconstruct an absolute path from a Claude project directory name."""
    if sys.platform == "win32":
        if encoded.startswith("C--"):
            reconstructed = "C:\\" + encoded[3:].replace("-", "\\")
            if os.path.isdir(reconstructed):
                return reconstructed
            for sep_char in ("/", "\\"):
                candidate = "C:" + sep_char + encoded[3:].replace("-", sep_char)
                if os.path.isdir(candidate):
                    return candidate
    else:
        if encoded.startswith("-"):
            candidate = "/" + encoded[1:].replace("-", "/")
            if os.path.isdir(candidate):
                return candidate
    return None


def _discover_claude_projects(home: Path | None = None) -> list[dict]:
    home = home or Path.home()
    projects_dir = home / ".claude" / "projects"
    if not projects_dir.is_dir():
        return []

    results = []
    for d in projects_dir.iterdir():
        if not d.is_dir():
            continue
        sessions = list(d.glob("*.jsonl"))
        if not sessions:
            continue
        decoded = _decode_claude_dir_name(d.name)
        if not decoded:
            continue
        latest = max(f.stat().st_mtime for f in sessions)
        results.append({
            "path": decoded,
            "tool": "claude",
            "session_count": len(sessions),
            "last_active": latest,
        })

    return results


def _discover_codex_projects(home: Path | None = None) -> list[dict]:
    home = home or Path.home()
    sess_root = home / ".codex" / "sessions"
    if not sess_root.is_dir():
        return []

    seen: dict[str, dict] = {}
    for f in sess_root.rglob("*.jsonl"):
        try:
            with open(f, encoding="utf-8") as fh:
                meta = json.loads(fh.readline())
            cwd = meta.get("payload", {}).get("cwd", "")
            if not cwd or not os.path.isdir(cwd):
                continue
            mtime = f.stat().st_mtime
            if cwd not in seen or mtime > seen[cwd]["last_active"]:
                seen[cwd] = {
                    "path": cwd,
                    "tool": "codex",
                    "session_count": seen.get(cwd, {}).get("session_count", 0) + 1,
                    "last_active": mtime,
                }
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    return list(seen.values())


GENERIC_DIRS = {"desktop", "documents", "downloads", "projects", "repos", "src", "home", "work"}


def _is_real_project(path: str) -> bool:
    """Filter out shallow paths and generic directories that aren't real projects."""
    p = Path(path)
    parts = p.parts
    min_depth = 5 if sys.platform == "win32" else 4
    if len(parts) < min_depth:
        return False
    if p.name.lower() in GENERIC_DIRS:
        return False
    return True


def discover_projects(home: Path | None = None) -> list[dict]:
    """Find projects from Claude and Codex session history.

    Returns a de-duplicated list sorted by most recently active first.
    Each entry has: path, tool, session_count, last_active.
    """
    claude = _discover_claude_projects(home)
    codex = _discover_codex_projects(home)

    by_path: dict[str, dict] = {}
    for p in claude + codex:
        if not _is_real_project(p["path"]):
            continue
        key = p["path"].lower() if sys.platform == "win32" else p["path"]
        if key not in by_path or p["last_active"] > by_path[key]["last_active"]:
            by_path[key] = p

    return sorted(by_path.values(), key=lambda p: p["last_active"], reverse=True)


def projects_to_config(projects: list[dict]) -> dict:
    """Convert discovered projects into a multideck config dict."""
    common_prefix = os.path.commonpath([p["path"] for p in projects]) if projects else ""

    leaf_counts = Counter(Path(p["path"]).name for p in projects)
    dup_leaves = {name for name, count in leaf_counts.items() if count > 1}

    palette = [
        "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ef4444", "#06b6d4",
        "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#6366f1", "#eab308",
    ]

    config_projects = []
    for i, p in enumerate(projects):
        try:
            rel = os.path.relpath(p["path"], common_prefix).replace("\\", "/")
        except ValueError:
            rel = p["path"].replace("\\", "/")

        entry: dict = {"path": rel}
        parts = rel.split("/")
        if len(parts) > 1:
            entry["group"] = parts[0]
        if parts[-1] in dup_leaves:
            entry["title"] = rel.replace("/", "-")
        if p["tool"] != "claude":
            entry["tool"] = p["tool"]
        entry["color"] = palette[i % len(palette)]
        config_projects.append(entry)

    return {
        "baseDir": common_prefix.replace("\\", "/"),
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
        "projects": config_projects,
    }
