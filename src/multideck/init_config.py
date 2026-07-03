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
