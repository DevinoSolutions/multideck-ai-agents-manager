from __future__ import annotations

import functools
import shutil
import sys


UNIX_TERMINAL_PRIORITY = [
    "kitty",
    "alacritty",
    "gnome-terminal",
    "konsole",
    "xterm",
]

MACOS_TERMINAL_PRIORITY = [
    "kitty",
]


@functools.cache
def detect_terminal() -> str:
    if sys.platform == "win32":
        return "wt"

    for name in UNIX_TERMINAL_PRIORITY:
        if shutil.which(name):
            return name

    if sys.platform == "darwin":
        return "terminal.app"

    raise RuntimeError(
        "No supported terminal emulator found. "
        "Install one of: kitty, alacritty, gnome-terminal, konsole, xterm"
    )
