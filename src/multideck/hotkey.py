"""Global Alt+V hotkey listener for clipboard image upload to psmux sessions."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError

if sys.platform != "win32":
    raise ImportError("hotkey module is Windows-only")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetClipboardData.restype = ctypes.c_void_p
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]

user32.CallNextHookEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int,
    ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]
user32.CallNextHookEx.restype = ctypes.c_long

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, ctypes.c_void_p,
    ctypes.c_void_p, ctypes.wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = ctypes.c_void_p

user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
kernel32.GetExitCodeProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = ctypes.wintypes.BOOL
kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]

VK_V = 0x56
VK_MENU = 0x12
VK_LMENU = 0xA4
VK_RMENU = 0xA5
# A low-level keyboard hook reports the physical Alt as VK_LMENU/VK_RMENU,
# never the generic VK_MENU -- match all three or Alt is never detected.
_ALT_KEYS = (VK_MENU, VK_LMENU, VK_RMENU)
CF_DIB = 8
BI_BITFIELDS = 3
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
HC_ACTION = 0

MD_TITLE_PREFIX = "md:"

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


def get_active_window_title() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def clipboard_has_image() -> bool:
    if not user32.OpenClipboard(None):
        return False
    try:
        return bool(user32.IsClipboardFormatAvailable(CF_DIB))
    finally:
        user32.CloseClipboard()


def get_clipboard_image() -> bytes | None:
    if not user32.OpenClipboard(None):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_DIB):
            return None
        handle = user32.GetClipboardData(CF_DIB)
        if not handle:
            return None

        size = kernel32.GlobalSize(handle)
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            dib_data = bytearray(ctypes.string_at(ptr, size))
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()

    return _dib_to_bmp(dib_data)


def _dib_to_bmp(dib: bytearray) -> bytes | None:
    """Wrap a clipboard DIB in a BMP file header.

    Two things the naive `14 + header_size` offset gets wrong:
      * BI_BITFIELDS DIBs (what GDI / .NET / many screenshot tools produce)
        store 3 color masks (12 bytes) between a BITMAPINFOHEADER and the
        pixels. Skipping them points the pixel offset 12 bytes too early, so
        decoders read masks as pixels and the image renders as garbage/black.
      * 32bpp DIBs usually carry an all-zero alpha channel. BMP's 4th byte is
        officially reserved, but many decoders honor it as alpha -> the whole
        image is treated as transparent and composites to black.
    """
    if len(dib) < 40:
        return None
    header_size = int.from_bytes(dib[0:4], "little")
    bpp = int.from_bytes(dib[14:16], "little")
    compression = int.from_bytes(dib[16:20], "little")
    clr_used = int.from_bytes(dib[32:36], "little")

    extra = 0
    # Masks only trail a plain BITMAPINFOHEADER; V4/V5 headers embed them.
    if compression == BI_BITFIELDS and header_size == 40:
        extra += 12
    if bpp <= 8:
        extra += (clr_used or (1 << bpp)) * 4

    px_start = header_size + extra

    if bpp == 32 and px_start < len(dib):
        n = len(range(px_start + 3, len(dib), 4))
        dib[px_start + 3::4] = b"\xff" * n

    file_size = 14 + len(dib)
    offset = 14 + px_start
    bmp_header = (
        b"BM"
        + file_size.to_bytes(4, "little")
        + b"\x00\x00\x00\x00"
        + offset.to_bytes(4, "little")
    )
    return bmp_header + bytes(dib)


def project_from_title(title: str) -> str | None:
    if title.startswith(MD_TITLE_PREFIX):
        return title[len(MD_TITLE_PREFIX):]
    return None


def upload_image(server_url: str, project: str, image_data: bytes) -> bool:
    boundary = "----MultideckUpload"
    body = (
        f"------MultideckUpload\r\n"
        f'Content-Disposition: form-data; name="project"\r\n'
        f"\r\n"
        f"{project}\r\n"
        f"------MultideckUpload\r\n"
        f'Content-Disposition: form-data; name="inject"\r\n'
        f"\r\n"
        f"1\r\n"
        f"------MultideckUpload\r\n"
        f'Content-Disposition: form-data; name="file"; filename="clipboard.bmp"\r\n'
        f"Content-Type: image/bmp\r\n"
        f"\r\n"
    ).encode() + image_data + b"\r\n------MultideckUpload--\r\n"

    # ?project= lets the server flash "uploading" in the md:<project> status line
    # the moment the request lands -- before it reads the image bytes -- so the
    # feedback shows in the same window you pasted into.
    req = Request(
        f"{server_url}/upload?project={quote(project)}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary=----MultideckUpload"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except (URLError, OSError, json.JSONDecodeError):
        return False


# --- Background-listener lifecycle -------------------------------------------
# attach starts the Alt+V listener hidden in the background (no terminal of its
# own), because its progress now shows in the md: windows. A pid file lets
# `multideck status` report it and `multideck down --all` stop it.

_PID_PATH = Path.home() / ".multideck" / "hotkey.pid"
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.wintypes.DWORD()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def listener_pid() -> int | None:
    """PID of the running Alt+V listener, or None. Clears a stale pid file."""
    try:
        pid = int(_PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return None
    if _pid_alive(pid):
        return pid
    try:
        _PID_PATH.unlink()
    except OSError:
        pass
    return None


def stop_listener() -> bool:
    """Stop the running Alt+V listener. Returns True if one was stopped."""
    import subprocess

    pid = listener_pid()
    if not pid:
        return False
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    try:
        _PID_PATH.unlink()
    except OSError:
        pass
    return True


def _write_pid() -> None:
    try:
        _PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PID_PATH.write_text(str(os.getpid()))
    except OSError:
        pass


def _clear_pid() -> None:
    try:
        if _PID_PATH.read_text().strip() == str(os.getpid()):
            _PID_PATH.unlink()
    except OSError:
        pass


def _do_upload(server_url: str, project: str) -> None:
    """Run upload in a thread so the hook callback returns quickly.

    No feedback is printed here: progress shows in the md:<project> window's own
    status line, driven by the upload server (see upload_server._flash).
    """
    image_data = get_clipboard_image()
    if image_data:
        upload_image(server_url, project, image_data)


def run_hotkey(server_url: str, session_names: set[str] | None = None) -> None:
    alt_held = False

    def hook_proc(nCode, wParam, lParam):
        nonlocal alt_held

        if nCode != HC_ACTION:
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

        if kb.vkCode in _ALT_KEYS:
            alt_held = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            return user32.CallNextHookEx(None, nCode, wParam, lParam)

        if kb.vkCode == VK_V and alt_held and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            title = get_active_window_title()
            project = project_from_title(title)

            if project is None:
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            if session_names and project not in session_names:
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            if not clipboard_has_image():
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            threading.Thread(target=_do_upload, args=(server_url, project), daemon=True).start()
            return 1

        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    hook_fn = HOOKPROC(hook_proc)

    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_fn, None, 0)
    if not hook:
        raise RuntimeError("Failed to install keyboard hook")

    # Record the pid only once the hook is actually installed, so a failed
    # listener never leaves a pid file claiming it's running.
    _write_pid()
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnhookWindowsHookEx(hook)
        _clear_pid()
