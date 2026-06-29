from __future__ import annotations

import ctypes
import ctypes.wintypes
import subprocess
from ctypes import POINTER, WINFUNCTYPE, byref, create_unicode_buffer, windll
from typing import Any

import shutil

from multideck.grid import MonitorRect, Rect
from multideck.platform import Platform, PsmuxWindowOpts, TerminalLaunchOpts, VSCodeLaunchOpts, find_psmux

user32 = windll.user32
shcore = windll.shcore


class WindowsPlatform(Platform):
    def set_dpi_aware(self) -> None:
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        except (OSError, AttributeError):
            pass
        try:
            shcore.SetProcessDpiAwareness(2)
            return
        except (OSError, AttributeError):
            pass
        try:
            user32.SetProcessDPIAware()
        except (OSError, AttributeError):
            pass

    def list_monitors(self) -> list[MonitorRect]:
        monitors: list[MonitorRect] = []

        MONITORINFOF_PRIMARY = 0x00000001

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("rcMonitor", ctypes.wintypes.RECT),
                ("rcWork", ctypes.wintypes.RECT),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("szDevice", ctypes.c_wchar * 32),
            ]

        MONITORENUMPROC = WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
            POINTER(ctypes.wintypes.RECT), ctypes.c_void_p,
        )

        def callback(hmon, hdc, lprect, lparam):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            user32.GetMonitorInfoW(hmon, byref(info))
            wa = info.rcWork
            is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)

            scale = 1.0
            try:
                dpi_x = ctypes.c_uint()
                dpi_y = ctypes.c_uint()
                shcore.GetDpiForMonitor(hmon, 0, byref(dpi_x), byref(dpi_y))
                scale = dpi_x.value / 96.0
            except (OSError, AttributeError):
                pass

            monitors.append(MonitorRect(
                x=wa.left,
                y=wa.top,
                w=wa.right - wa.left,
                h=wa.bottom - wa.top,
                is_primary=is_primary,
                scale_factor=scale,
            ))
            return 1

        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
        return monitors

    def find_window(self, title: str, mode: str = "exact") -> int | None:
        result: int | None = None

        WNDENUMPROC = WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _):
            nonlocal result
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            text = buf.value
            if mode == "exact" and text == title:
                result = hwnd
                return False
            if mode == "contains" and title.lower() in text.lower():
                result = hwnd
                return False
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return result

    def snapshot_windows(self) -> dict[str, int]:
        titles: dict[str, int] = {}
        WNDENUMPROC = WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if buf.value:
                titles[buf.value] = hwnd
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return titles

    def move_window(self, handle: Any, rect: Rect) -> None:
        user32.MoveWindow(handle, rect.x, rect.y, rect.w, rect.h, True)
        user32.MoveWindow(handle, rect.x, rect.y, rect.w, rect.h, True)

    def launch_terminal(self, opts: TerminalLaunchOpts) -> None:
        args = [
            "wt", "-w", "new",
            "-d", opts.cwd,
            "--title", opts.title,
        ]
        if opts.color:
            args.extend(["--tabColor", opts.color])
        args.append("--suppressApplicationTitle")

        if opts.ssh_host:
            remote_dir = opts.ssh_remote_dir or opts.cwd
            inner = f"cd {remote_dir} && {opts.command}"
            if opts.ssh_shell:
                remote = f"{opts.ssh_shell} '{inner}'"
            else:
                remote = inner
            # Pass ssh + args as separate argv elements so the remote command
            # is a single, cleanly-quoted token. Building one `ssh ... "..."`
            # string and handing it to `cmd /k` double-nests the quotes, which
            # cmd mangles (the inner quotes leak to the remote shell).
            args.extend(["--", "cmd", "/k", "ssh", "-t", opts.ssh_host, remote])
        else:
            args.extend(["--", "cmd", "/k", opts.command])

        subprocess.Popen(args)

    def launch_vscode(self, opts: VSCodeLaunchOpts) -> None:
        args = ["cmd", "/c", opts.command]
        if opts.ssh_host:
            args.extend(["--remote", f"ssh-remote+{opts.ssh_host}"])
        args.append(opts.dir)
        subprocess.Popen(args)

    def launch_psmux_session(self, windows: list[PsmuxWindowOpts]) -> None:
        psmux = find_psmux()
        if not psmux:
            raise FileNotFoundError("psmux not found on PATH")
        if not windows:
            return

        checks = [(w, subprocess.Popen([psmux, "-L", w.window_name, "has-session"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                   for w in windows]
        to_create = [w for w, p in checks if p.wait() != 0]

        if not to_create:
            return

        kills = [subprocess.Popen([psmux, "-L", w.window_name, "kill-server"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 for w in to_create]
        for p in kills:
            p.wait()

        creates = [subprocess.Popen(
                       [psmux, "-L", w.window_name, "new-session", "-d",
                        "-s", w.window_name, "-c", w.cwd],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                   for w in to_create]
        for p in creates:
            if p.wait() != 0:
                raise subprocess.CalledProcessError(p.returncode, p.args)

        for w in to_create:
            subprocess.Popen(
                [psmux, "-L", w.window_name, "send-keys",
                 "-t", w.window_name, f"cmd /c {w.command}", "Enter"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def attach_psmux(self, session_name: str, title: str,
                     color: str | None = None,
                     config_path: str | None = None) -> None:
        psmux = find_psmux()
        if not psmux:
            return
        args = [
            "wt", "-w", "new",
            "--title", title,
        ]
        if color:
            args.extend(["--tabColor", color])
        args.append("--suppressApplicationTitle")
        args.extend(["--", psmux, "-L", session_name, "attach"])
        subprocess.Popen(args)


