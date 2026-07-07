from __future__ import annotations

import functools
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from multideck.grid import MonitorRect, Rect


@functools.lru_cache(maxsize=1)
def find_psmux() -> str | None:
    found = shutil.which("psmux")
    if found:
        return found
    if sys.platform == "win32":
        from multideck.env import (
            localappdata_dir,
        )  # heavy subsystem: in-body per policy

        local = localappdata_dir() / "psmux" / "psmux.exe"
        if local.is_file():
            return str(local)
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
    def find_window(
        self, title: str, mode: Literal["exact", "contains"] = "exact"
    ) -> object | None: ...

    @abstractmethod
    def move_window(self, handle: object, rect: Rect) -> None: ...

    @abstractmethod
    def launch_terminal(self, opts: TerminalLaunchOpts) -> None: ...

    @abstractmethod
    def launch_vscode(self, opts: VSCodeLaunchOpts) -> None: ...

    def snapshot_windows(self) -> dict[str, object]:
        """Return {title: handle} for all visible windows in a single pass."""
        return {}

    def launch_psmux_session(self, windows: list[PsmuxWindowOpts]) -> None:
        raise NotImplementedError("psmux is only supported on Windows")

    def attach_psmux(
        self,
        session_name: str,
        title: str,
        color: str | None = None,
        config_path: str | None = None,
    ) -> None:
        raise NotImplementedError("psmux is only supported on Windows")

    def supports_psmux(self) -> bool:
        """True if this platform can run persistent psmux sessions."""
        return False

    def supports_hotkey(self) -> bool:
        """True if this platform can run the Alt+V clipboard-image listener."""
        return False

    def supports_attention_signals(self) -> bool:
        """True if this platform can badge titles / flash / focus windows."""
        return False

    def set_window_title(self, handle: object, title: str) -> bool:
        """Rewrite a window's title in place. False = unsupported or failed."""
        return False

    def flash_window(self, handle: object) -> bool:
        """Flash the window's taskbar presence to request the user's attention."""
        return False

    def focus_window(self, handle: object) -> bool:
        """Restore (if minimized) and bring the window to the foreground."""
        return False


def get_platform() -> Platform:
    if sys.platform == "win32":
        from multideck.platform.windows import WindowsPlatform

        return WindowsPlatform()
    if sys.platform == "darwin":
        from multideck.platform.macos import MacOSPlatform

        return MacOSPlatform()
    from multideck.platform.linux import LinuxPlatform

    return LinuxPlatform()
