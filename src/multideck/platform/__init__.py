from __future__ import annotations

import os
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from multideck.grid import Rect, MonitorRect


def find_psmux() -> str | None:
    found = shutil.which("psmux")
    if found:
        return found
    if sys.platform == "win32":
        local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "psmux", "psmux.exe")
        if os.path.isfile(local):
            return local
    return None


@dataclass
class TerminalLaunchOpts:
    title: str
    cwd: str
    command: str
    color: str | None = None
    ssh_host: str | None = None
    ssh_remote_dir: str | None = None
    ssh_shell: str = "bash -lc"


@dataclass
class PsmuxWindowOpts:
    window_name: str
    cwd: str
    command: str


@dataclass
class VSCodeLaunchOpts:
    dir: str
    ssh_host: str | None = None
    command: str = "code"


class Platform(ABC):
    @abstractmethod
    def set_dpi_aware(self) -> None: ...

    @abstractmethod
    def list_monitors(self) -> list[MonitorRect]: ...

    @abstractmethod
    def find_window(self, title: str, mode: str = "exact") -> Any | None: ...

    @abstractmethod
    def move_window(self, handle: Any, rect: Rect) -> None: ...

    @abstractmethod
    def launch_terminal(self, opts: TerminalLaunchOpts) -> None: ...

    @abstractmethod
    def launch_vscode(self, opts: VSCodeLaunchOpts) -> None: ...

    def launch_psmux_session(self, windows: list[PsmuxWindowOpts]) -> None:
        raise NotImplementedError("psmux is only supported on Windows")


def get_platform() -> Platform:
    if sys.platform == "win32":
        from multideck.platform.windows import WindowsPlatform
        return WindowsPlatform()
    elif sys.platform == "darwin":
        from multideck.platform.macos import MacOSPlatform
        return MacOSPlatform()
    else:
        from multideck.platform.linux import LinuxPlatform
        return LinuxPlatform()
