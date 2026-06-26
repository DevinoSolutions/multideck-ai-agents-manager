"""Cross-platform feedback for the Alt+V clipboard-upload hotkey.

The hotkey otherwise gives no signal until the pasted path lands in the session,
which means silence while an upload is in flight (and up to the request timeout
if the host is slow or unreachable). This adds three layers, each best-effort:

  * an immediate beep the moment a paste is captured / resolved,
  * a colored status line in the listener's terminal,
  * a native desktop notification via the OS's own tool.

Design goal: work the same on Windows, macOS, and Linux with the least possible
per-OS surface -- no GUI toolkit, no third-party dependency. The only platform
branches are the one-line beep and a three-way map of notification commands.
Everything is wrapped so a failure to notify can never break an upload. Set
``MULTIDECK_NO_FEEDBACK=1`` to disable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

APP = "multideck"

# stage -> (unicode glyph, ANSI color, notification title)
_STAGES = {
    "start": ("↑", "36", "Uploading image"),   # up arrow, cyan
    "ok":    ("✓", "32", "Image delivered"),    # check, green
    "fail":  ("✗", "31", "Upload failed"),      # cross, red
}
# ASCII fallbacks for terminals that can't encode the glyphs (e.g. cp1252).
_ASCII = {"start": ">>", "ok": "OK", "fail": "!!"}

# stage -> winsound.MessageBeep type (Windows only; MB_OK / ASTERISK / HAND)
_TONES = {"start": 0x00000000, "ok": 0x00000040, "fail": 0x00000010}

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Tray-balloon toast via built-in .NET WinForms -- no module install required.
# Values arrive via env vars so project names with quotes/spaces are safe.
_PS_BALLOON = (
    "$ErrorActionPreference='SilentlyContinue';"
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
    "$icon=if($env:MD_ICON -eq 'error')"
    "{[System.Windows.Forms.ToolTipIcon]::Error}else{[System.Windows.Forms.ToolTipIcon]::Info};"
    "$n=New-Object System.Windows.Forms.NotifyIcon;"
    "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
    "$n.ShowBalloonTip(3000,$env:MD_TITLE,$env:MD_MSG,$icon);"
    "1..30|%{[System.Windows.Forms.Application]::DoEvents();Start-Sleep -Milliseconds 100};"
    "$n.Dispose()"
)


def enabled() -> bool:
    return os.environ.get("MULTIDECK_NO_FEEDBACK", "") in ("", "0", "false", "False")


def begin(project: str):
    """Signal that a paste was captured: instant beep + console line.

    No desktop toast here -- the beep is the immediate "I heard you" cue, and a
    second toast now plus another on the result would just be noise on a fast
    upload. Returns a handle to pass to finish().
    """
    if not enabled():
        return None
    play_tone("start")
    _console("start", project)
    return project


def finish(handle, project: str, ok: bool) -> None:
    """Resolve the feedback: result beep + console line + a single desktop toast."""
    if not enabled():
        return
    stage = "ok" if ok else "fail"
    play_tone(stage)
    _console(stage, project)
    # The native notifier may spawn a process / block briefly -- never on the
    # caller's thread.
    threading.Thread(target=_notify, args=(stage, project), daemon=True).start()


def play_tone(stage: str) -> None:
    """Immediate audible cue: winsound on Windows, terminal bell elsewhere."""
    if not enabled():
        return
    if sys.platform == "win32":
        try:
            import winsound
            winsound.MessageBeep(_TONES.get(stage, 0x00000000))
            return
        except Exception:
            pass
    try:
        sys.stderr.write("\a")
        sys.stderr.flush()
    except Exception:
        pass


def _console(stage: str, project: str) -> None:
    glyph, color, _ = _STAGES[stage]
    try:
        print(f"  \033[{color}m{glyph} {project}\033[0m", flush=True)
    except UnicodeEncodeError:
        print(f"  {_ASCII[stage]} {project}", flush=True)
    except Exception:
        pass


def _notify_spec(stage: str, project: str, platform: str):
    """Build the native-notification command for a platform.

    Returns (argv, env_overrides) or None if the platform has no known tool.
    Kept pure (platform passed in) so it can be unit-tested off-host.
    """
    _, _, title = _STAGES[stage]
    message = project
    if platform == "darwin":
        script = ('display notification (system attribute "MD_MSG") '
                  'with title (system attribute "MD_TITLE")')
        return ["osascript", "-e", script], {"MD_TITLE": title, "MD_MSG": message}
    if platform == "win32":
        return (
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_BALLOON],
            {"MD_TITLE": title, "MD_MSG": message, "MD_ICON": "error" if stage == "fail" else "info"},
        )
    if platform.startswith("linux") or "bsd" in platform:
        urgency = "critical" if stage == "fail" else "normal"
        return ["notify-send", "-a", APP, "-u", urgency, "-t", "4000", title, message], {}
    return None


def _notify(stage: str, project: str) -> None:
    spec = _notify_spec(stage, project, sys.platform)
    if not spec:
        return
    argv, env_over = spec
    if not shutil.which(argv[0]):
        return
    try:
        subprocess.run(
            argv,
            env={**os.environ, **env_over},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        pass
