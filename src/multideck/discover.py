from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from urllib.parse import unquote, urlparse

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


def _vscode_storage_dir() -> Path | None:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", ""))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "Code" / "User" / "workspaceStorage"
    return d if d.is_dir() else None


def _uri_to_path(uri: str) -> str | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if sys.platform == "win32" and path.startswith("/"):
        path = path[1:]
    return path


def _discover_vscode_projects() -> list[dict]:
    storage = _vscode_storage_dir()
    if not storage:
        return []

    results = []
    for d in storage.iterdir():
        wj = d / "workspace.json"
        if not wj.is_file():
            continue
        try:
            data = json.loads(wj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        folder_uri = data.get("folder", "")
        if not folder_uri:
            continue
        folder = _uri_to_path(folder_uri)
        if not folder or not os.path.isdir(folder):
            continue
        mtime = d.stat().st_mtime
        results.append({
            "path": folder,
            "tool": "vscode",
            "session_count": 1,
            "last_active": mtime,
        })

    return results


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


STEP_DAYS = 3
MIN_PROJECTS = 3
MAX_STEPS = 160


def discover_projects(home: Path | None = None) -> tuple[list[dict], int]:
    """Find projects from Claude and Codex session history.

    Expands the time window (3 days, 6, 9, ...) until at least
    MIN_PROJECTS are found or MAX_STEPS is reached.

    Returns (projects, days_searched).
    """
    import time

    home = home or Path.home()
    codex = _discover_codex_projects(home)
    vscode = _discover_vscode_projects()

    by_path: dict[str, dict] = {}
    matched_encoded: set[str] = set()

    def _norm_key(path: str) -> str:
        k = os.path.normpath(path)
        return k.lower() if sys.platform == "win32" else k

    for p in codex + vscode:
        if not _is_real_project(p["path"]):
            continue
        p["path"] = os.path.normpath(p["path"])
        key = _norm_key(p["path"])

        claude_info = _claude_sessions_for_path(p["path"], home)
        if claude_info:
            encoded = encode_claude_project_path(p["path"])
            matched_encoded.add(encoded)
            if claude_info["last_active"] >= p.get("last_active", 0):
                by_path[key] = {
                    "path": p["path"],
                    "tool": "claude",
                    "session_count": claude_info["session_count"],
                    "last_active": claude_info["last_active"],
                }
                continue

        if key not in by_path or p["last_active"] > by_path[key]["last_active"]:
            by_path[key] = p

    for p in _discover_claude_standalone(home, matched_encoded):
        if not _is_real_project(p["path"]):
            continue
        p["path"] = os.path.normpath(p["path"])
        key = _norm_key(p["path"])
        if key not in by_path or p["last_active"] > by_path[key]["last_active"]:
            by_path[key] = p

    all_projects = sorted(by_path.values(), key=lambda p: p["last_active"], reverse=True)
    if not all_projects:
        return [], 0

    now = time.time()
    for step in range(1, MAX_STEPS + 1):
        days = step * STEP_DAYS
        cutoff = now - (days * 86400)
        recent = [p for p in all_projects if p["last_active"] >= cutoff]
        if len(recent) >= MIN_PROJECTS:
            return recent, days

    return all_projects, MAX_STEPS * STEP_DAYS


def _find_base_dir(paths: list[str]) -> str:
    """Find the deepest directory shared by at least 60% of projects."""
    if not paths:
        return ""
    threshold = max(3, int(len(paths) * 0.6))
    candidate = os.path.commonpath(paths)

    while True:
        children: dict[str, int] = {}
        for p in paths:
            try:
                rel = os.path.relpath(p, candidate)
            except ValueError:
                continue
            first = rel.split(os.sep)[0]
            if first and first != ".":
                children[first] = children.get(first, 0) + 1

        best = max(children, key=children.get) if children else None
        if best and children[best] >= threshold:
            candidate = os.path.join(candidate, best)
        else:
            break

    return candidate


def projects_to_config(projects: list[dict]) -> dict:
    paths = [p["path"] for p in projects]
    base_dir = _find_base_dir(paths) if projects else ""

    leaf_counts = Counter(Path(p["path"]).name for p in projects)
    dup_leaves = {name for name, count in leaf_counts.items() if count > 1}

    palette = [
        "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ef4444", "#06b6d4",
        "#ec4899", "#84cc16", "#f97316", "#14b8a6", "#6366f1", "#eab308",
    ]

    config_projects = []
    for i, p in enumerate(projects):
        try:
            rel = os.path.relpath(p["path"], base_dir).replace("\\", "/")
        except ValueError:
            rel = p["path"].replace("\\", "/")

        entry: dict = {"path": rel}

        parent = Path(p["path"]).parent.name.lower()
        if parent and parent not in GENERIC_DIRS and parent != Path(base_dir).name.lower():
            entry["group"] = Path(p["path"]).parent.name

        if parts := rel.split("/"):
            if parts[-1] in dup_leaves:
                entry["title"] = rel.replace("/", "-")

        if p["tool"] != "claude":
            entry["tool"] = p["tool"]
        entry["color"] = palette[i % len(palette)]
        config_projects.append(entry)

    return {
        "baseDir": base_dir.replace("\\", "/"),
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
