from __future__ import annotations

import os
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
