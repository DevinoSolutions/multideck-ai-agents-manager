#!/usr/bin/env python
"""Single source of truth for the multideck quality gate.

    uv run python scripts/check.py      # or: python scripts/check.py

Runs on the current interpreter; CI additionally runs `compileall` across the
full 3.10-3.14 matrix (see ci.yml). Exits non-zero on the first failing step.
"""
from __future__ import annotations

import subprocess
import sys

STEPS: list[tuple[str, list[str]]] = [
    ("ruff  (lint + 3.10 syntax floor)", ["ruff", "check", "src"]),
    ("compileall (current interpreter)", [sys.executable, "-m", "compileall", "-q", "src"]),
    ("mypy  (type check)", [sys.executable, "-m", "mypy"]),
    ("pytest + coverage", [sys.executable, "-m", "pytest", "tests/unit/",
                            "--cov=multideck", "--cov-report=term-missing"]),
]


def main() -> int:
    failed: list[str] = []
    for name, cmd in STEPS:
        print(f"\n=== {name} ===", flush=True)
        if subprocess.run(cmd).returncode != 0:
            failed.append(name)
    if failed:
        print("\nGATE FAILED: " + ", ".join(failed))
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
