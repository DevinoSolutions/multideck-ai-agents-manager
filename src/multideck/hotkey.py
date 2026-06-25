"""Global Alt+V hotkey listener for clipboard image upload to psmux sessions."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import sys
import threading
import time
from pathlib import Path
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

VK_V = 0x56
VK_MENU = 0x12
CF_DIB = 8
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
            dib_data = ctypes.string_at(ptr, size)
            header_size = int.from_bytes(dib_data[:4], "little")
            file_size = 14 + size
            offset = 14 + header_size
            bmp_header = (
                b"BM"
                + file_size.to_bytes(4, "little")
                + b"\x00\x00\x00\x00"
                + offset.to_bytes(4, "little")
            )
            return bmp_header + dib_data
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


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

    req = Request(
        f"{server_url}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary=----MultideckUpload"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except (URLError, OSError, json.JSONDecodeError):
        return False


def _do_upload(server_url: str, project: str) -> None:
    """Run upload in a thread so the hook callback returns quickly."""
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

        if kb.vkCode == VK_MENU:
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

    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        user32.UnhookWindowsHookEx(hook)
