from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from multideck.sessions.claude import encode_claude_project_path


def _claude_sessions_for_path(project_path: str, home: Path | None = None) -> dict | None:
    """Check if Claude has sessions for a given project path."""
    home = home or Path.home()
    encoded = encode_claude_project_path(project_path)
    sess_dir = home / ".claude" / "projects" / encoded
    if not sess_dir.is_dir():
        return None
    sessions = list(sess_dir.glob("*.jsonl"))
    if not sessions:
        return None
    return {
        "session_count": len(sessions),
        "last_active": max(f.stat().st_mtime for f in sessions),
    }


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
            key = cwd.lower() if sys.platform == "win32" else cwd
            prev = seen.get(key)
            seen[key] = {
                "path": cwd,
                "tool": "codex",
                "session_count": (prev["session_count"] if prev else 0) + 1,
                "last_active": max(mtime, prev["last_active"] if prev else 0),
            }
        except (json.JSONDecodeError, KeyError, OSError):
            continue

    return list(seen.values())


def _discover_claude_standalone(home: Path | None = None, known_encoded: set[str] | None = None) -> list[dict]:
    """Discover Claude projects that weren't found via Codex (brute-force decode)."""
    home = home or Path.home()
    projects_dir = home / ".claude" / "projects"
    if not projects_dir.is_dir():
        return []

    known_encoded = known_encoded or set()
    results = []

    for d in projects_dir.iterdir():
        if not d.is_dir() or d.name in known_encoded:
            continue
        sessions = list(d.glob("*.jsonl"))
        if not sessions:
            continue
        decoded = _try_decode(d.name)
        if not decoded:
            continue
        results.append({
            "path": decoded,
            "tool": "claude",
            "session_count": len(sessions),
            "last_active": max(f.stat().st_mtime for f in sessions),
        })

    return results


def _try_decode(encoded: str) -> str | None:
    """Best-effort decode of a Claude project directory name."""
    if sys.platform == "win32":
        if not encoded.startswith("C--"):
            return None
        rest = encoded[3:]
        candidate = "C:\\" + rest.replace("-", "\\")
        if os.path.isdir(candidate):
            return candidate
    else:
        if not encoded.startswith("-"):
            return None
        candidate = "/" + encoded[1:].replace("-", "/")
        if os.path.isdir(candidate):
            return candidate
    return None


GENERIC_DIRS = {"desktop", "documents", "downloads", "projects", "repos", "src", "home", "work"}


def _is_real_project(path: str) -> bool:
    p = Path(path)
    parts = p.parts
    min_depth = 5 if sys.platform == "win32" else 4
    if len(parts) < min_depth:
        return False
    if p.name.lower() in GENERIC_DIRS:
        return False
    return True


RECENT_DAYS = 30


def discover_projects(
    home: Path | None = None,
    recent_days: int = RECENT_DAYS,
) -> list[dict]:
    """Find projects from Claude and Codex session history.

    Strategy: discover paths from Codex (reliable), then cross-reference
    each path against Claude sessions. Claude projects not found via Codex
    are decoded with best-effort fallback.
    """
    import time

    home = home or Path.home()
    codex = _discover_codex_projects(home)

    by_path: dict[str, dict] = {}
    matched_encoded: set[str] = set()

    for p in codex:
        if not _is_real_project(p["path"]):
            continue
        key = p["path"].lower() if sys.platform == "win32" else p["path"]

        claude_info = _claude_sessions_for_path(p["path"], home)
        if claude_info:
            encoded = encode_claude_project_path(p["path"])
            matched_encoded.add(encoded)
            if claude_info["last_active"] >= p["last_active"]:
                by_path[key] = {
                    "path": p["path"],
                    "tool": "claude",
                    "session_count": claude_info["session_count"],
                    "last_active": claude_info["last_active"],
                }
                continue

        by_path[key] = p

    for p in _discover_claude_standalone(home, matched_encoded):
        if not _is_real_project(p["path"]):
            continue
        key = p["path"].lower() if sys.platform == "win32" else p["path"]
        if key not in by_path or p["last_active"] > by_path[key]["last_active"]:
            by_path[key] = p

    all_projects = sorted(by_path.values(), key=lambda p: p["last_active"], reverse=True)
    if not all_projects:
        return []

    cutoff = time.time() - (recent_days * 86400)
    recent = [p for p in all_projects if p["last_active"] >= cutoff]

    if len(recent) >= 5:
        return recent
    return all_projects[:max(5, len(recent))]


def projects_to_config(projects: list[dict]) -> dict:
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
