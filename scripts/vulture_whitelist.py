"""Vulture whitelist rationale.

The ignore_names entries in [tool.vulture] (pyproject.toml) are documented
here with full context. Every entry is a framework-required name that
vulture cannot see as used; genuinely dead code must be deleted, not added
to this list.

attach_port — cli/app.py: deprecated click option (--attach-port, hidden=True).
    The port is now read from host config. The parameter must remain because
    click binds it by name; removing it would break existing invocations.

hdc, lprect, lparam — platform/windows.py: positional parameters in the
    ctypes EnumDisplayMonitors callback (MONITORENUMPROC signature). Only
    hmon is used; the other three are required by the Win32 C ABI.
"""
