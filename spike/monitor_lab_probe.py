"""Monitor-lab feasibility probe (SPIKE — not shipped, not imported by the package).

Pure stdlib ctypes. Dumps Windows monitor topology + per-monitor DPI as JSON
lines, and drives the parsec-vdd virtual-display driver to answer the spike's
Q1-Q5. No pywin32, no third-party deps, so it runs against the bare
`pip install -e .` env on a hosted windows-latest runner.

Subcommands
-----------
  baseline               enumerate topology + multideck's own list_monitors()
  enumerate --tag T      same dump, tagged (post-driver snapshots)
  set-res --device D --w W --h H     ChangeDisplaySettingsEx on one monitor (Q3)
  set-dpi --device D --percent P     live per-monitor DPI via CCD API (Q4)
  parsec-battery --count N           open parsec-vdd, add N displays, then run
                                     Q2/Q3/Q4 in-process (handle held alive)
  parsec-hold --count N --seconds S  add N displays, ping-hold for S seconds
                                     (lets a separate `multideck --go` run — Q5)

Every line of stdout that begins with `{` is a JSON evidence record. Human
markers use `=== ... ===`.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
from ctypes import POINTER, byref, wintypes

# ---------------------------------------------------------------------------
# tiny JSON-lines emitter
# ---------------------------------------------------------------------------


def emit(kind: str, **fields: object) -> None:
    rec = {"kind": kind}
    rec.update(fields)
    sys.stdout.write(json.dumps(rec) + "\n")
    sys.stdout.flush()


def marker(text: str) -> None:
    sys.stdout.write(f"=== {text} ===\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# DPI awareness (so rects/DPI are physical, matching multideck's own path)
# ---------------------------------------------------------------------------

user32 = ctypes.windll.user32
shcore = ctypes.windll.shcore
kernel32 = ctypes.windll.kernel32
setupapi = ctypes.windll.setupapi


def set_dpi_aware() -> None:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_V2
        return
    except (OSError, AttributeError):
        pass
    try:
        shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Q2 — topology enumeration
# ---------------------------------------------------------------------------

MONITORINFOF_PRIMARY = 0x00000001
ENUM_CURRENT_SETTINGS = -1


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    POINTER(wintypes.RECT),
    ctypes.c_void_p,
)


def _monitor_dpi(hmon: int) -> dict[str, object]:
    out: dict[str, object] = {}
    for label, mdt in (("effective", 0), ("angular", 1), ("raw", 2)):
        dx, dy = ctypes.c_uint(0), ctypes.c_uint(0)
        try:
            hr = shcore.GetDpiForMonitor(hmon, mdt, byref(dx), byref(dy))
            out[label] = {"hr": hr, "x": dx.value, "y": dy.value}
        except (OSError, AttributeError) as exc:
            out[label] = {"error": str(exc)}
    eff = out.get("effective")
    if isinstance(eff, dict) and isinstance(eff.get("x"), int) and eff["x"]:
        out["scale_percent"] = round(eff["x"] / 96.0 * 100)
    return out


def enumerate_monitors(tag: str) -> None:
    def cb(hmon: int, _hdc: int, _lprect: object, _lp: int) -> int:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hmon, byref(info))
        m, w = info.rcMonitor, info.rcWork
        emit(
            "monitor",
            tag=tag,
            device=info.szDevice,
            primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
            rcMonitor=[m.left, m.top, m.right, m.bottom],
            rcWork=[w.left, w.top, w.right, w.bottom],
            size=[m.right - m.left, m.bottom - m.top],
            dpi=_monitor_dpi(hmon),
        )
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)


def enumerate_display_devices(tag: str) -> None:
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(None, i, byref(dd), 0):
            break
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        has_mode = bool(
            user32.EnumDisplaySettingsW(dd.DeviceName, ENUM_CURRENT_SETTINGS, byref(dm))
        )
        emit(
            "displaydevice",
            tag=tag,
            index=i,
            name=dd.DeviceName,
            string=dd.DeviceString,
            state_flags=hex(dd.StateFlags),
            active=bool(dd.StateFlags & 0x1),  # DISPLAY_DEVICE_ACTIVE
            mode=(
                {
                    "w": dm.dmPelsWidth,
                    "h": dm.dmPelsHeight,
                    "freq": dm.dmDisplayFrequency,
                    "bpp": dm.dmBitsPerPel,
                    "x": dm.dmPositionX,
                    "y": dm.dmPositionY,
                }
                if has_mode
                else None
            ),
        )
        i += 1


def enumerate_virtualscreen(tag: str) -> None:
    g = user32.GetSystemMetrics
    emit(
        "virtualscreen",
        tag=tag,
        x=g(76),
        y=g(77),
        w=g(78),
        h=g(79),
        cmonitors=g(80),
    )


def multideck_monitors(tag: str) -> None:
    try:
        from multideck.platform import get_platform

        plat = get_platform()
        plat.set_dpi_aware()
        for i, mon in enumerate(plat.list_monitors()):
            emit(
                "multideck_monitor",
                tag=tag,
                index=i,
                x=mon.x,
                y=mon.y,
                w=mon.w,
                h=mon.h,
                is_primary=mon.is_primary,
                scale_factor=mon.scale_factor,
            )
    except Exception as exc:  # noqa: BLE001 - spike: report anything
        emit("multideck_monitor_error", tag=tag, error=repr(exc))


def full_dump(tag: str) -> None:
    marker(f"TOPOLOGY DUMP tag={tag}")
    enumerate_virtualscreen(tag)
    enumerate_monitors(tag)
    enumerate_display_devices(tag)
    multideck_monitors(tag)


# ---------------------------------------------------------------------------
# Q3 — resolution change
# ---------------------------------------------------------------------------

DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
CDS_UPDATEREGISTRY = 0x00000001
CDS_RESET = 0x40000000


def set_resolution(device: str, w: int, h: int) -> None:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if not user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, byref(dm)):
        emit("setres", device=device, requested=[w, h], error="EnumDisplaySettings failed")
        return
    before = [dm.dmPelsWidth, dm.dmPelsHeight]
    dm.dmPelsWidth = w
    dm.dmPelsHeight = h
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
    ret = user32.ChangeDisplaySettingsExW(
        device, byref(dm), None, CDS_UPDATEREGISTRY, None
    )
    # DISP_CHANGE_SUCCESSFUL == 0
    after = DEVMODEW()
    after.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, byref(after))
    emit(
        "setres",
        device=device,
        requested=[w, h],
        before=before,
        ret_code=ret,
        ok=(ret == 0),
        after=[after.dmPelsWidth, after.dmPelsHeight],
    )


# ---------------------------------------------------------------------------
# Q4 — live per-monitor DPI via the CCD "reverse-engineered" API
# (ports imniko/SetDPI DpiHelper)
# ---------------------------------------------------------------------------

QDC_ONLY_ACTIVE_PATHS = 0x00000002
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DPI_GET = -3
DPI_SET = -4
DPI_VALS = [100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    # 64 bytes; union body treated as opaque (we only read paths' source info)
    _fields_ = [
        ("infoType", wintypes.UINT),
        ("id", wintypes.UINT),
        ("adapterId", LUID),
        ("blob", ctypes.c_byte * 48),
    ]


class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("size", wintypes.UINT),
        ("adapterId", LUID),
        ("id", wintypes.UINT),
    ]


class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", ctypes.c_wchar * 32),
    ]


class DPI_SCALE_GET(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("minScaleRel", ctypes.c_int32),
        ("curScaleRel", ctypes.c_int32),
        ("maxScaleRel", ctypes.c_int32),
    ]


class DPI_SCALE_SET(ctypes.Structure):
    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("scaleRel", ctypes.c_int32),
    ]


def _source_name_map() -> dict[str, tuple[LUID, int]]:
    r"""map \\.\DISPLAYn -> (adapterId, sourceId) for active paths."""
    num_paths = wintypes.UINT(0)
    num_modes = wintypes.UINT(0)
    rc = ctypes.windll.user32.GetDisplayConfigBufferSizes(
        QDC_ONLY_ACTIVE_PATHS, byref(num_paths), byref(num_modes)
    )
    if rc != 0:
        return {}
    paths = (DISPLAYCONFIG_PATH_INFO * num_paths.value)()
    modes = (DISPLAYCONFIG_MODE_INFO * num_modes.value)()
    rc = ctypes.windll.user32.QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS,
        byref(num_paths),
        paths,
        byref(num_modes),
        modes,
        None,
    )
    if rc != 0:
        return {}
    out: dict[str, tuple[LUID, int]] = {}
    for p in paths[: num_paths.value]:
        sdn = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
        sdn.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
        sdn.header.size = ctypes.sizeof(DISPLAYCONFIG_SOURCE_DEVICE_NAME)
        sdn.header.adapterId = p.sourceInfo.adapterId
        sdn.header.id = p.sourceInfo.id
        if ctypes.windll.user32.DisplayConfigGetDeviceInfo(byref(sdn.header)) == 0:
            out[sdn.viewGdiDeviceName] = (p.sourceInfo.adapterId, p.sourceInfo.id)
    return out


def _dpi_get(adapter: LUID, source_id: int) -> dict[str, int] | None:
    pkt = DPI_SCALE_GET()
    pkt.header.type = DPI_GET
    pkt.header.size = ctypes.sizeof(DPI_SCALE_GET)
    pkt.header.adapterId = adapter
    pkt.header.id = source_id
    if ctypes.windll.user32.DisplayConfigGetDeviceInfo(byref(pkt.header)) != 0:
        return None
    cur = max(pkt.minScaleRel, min(pkt.curScaleRel, pkt.maxScaleRel))
    min_abs = abs(pkt.minScaleRel)
    if len(DPI_VALS) < min_abs + pkt.maxScaleRel + 1:
        return None
    return {
        "current": DPI_VALS[min_abs + cur],
        "recommended": DPI_VALS[min_abs],
        "maximum": DPI_VALS[min_abs + pkt.maxScaleRel],
        "minimum": 100,
    }


def _dpi_set(adapter: LUID, source_id: int, percent: int) -> bool:
    info = _dpi_get(adapter, source_id)
    if not info:
        return False
    try:
        idx1 = DPI_VALS.index(percent)
        idx2 = DPI_VALS.index(info["recommended"])
    except ValueError:
        return False
    pkt = DPI_SCALE_SET()
    pkt.header.type = DPI_SET
    pkt.header.size = ctypes.sizeof(DPI_SCALE_SET)
    pkt.header.adapterId = adapter
    pkt.header.id = source_id
    pkt.scaleRel = idx1 - idx2
    return ctypes.windll.user32.DisplayConfigSetDeviceInfo(byref(pkt.header)) == 0


def _hmon_for_device(device: str) -> int | None:
    found: list[int] = []

    def cb(hmon: int, _hdc: int, _lprect: object, _lp: int) -> int:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hmon, byref(info))
        if info.szDevice == device:
            found.append(hmon)
            return 0
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return found[0] if found else None


def set_dpi(device: str, percent: int) -> None:
    smap = _source_name_map()
    if device not in smap:
        emit("setdpi", device=device, percent=percent,
             error="device not in source map", known=list(smap.keys()))
        return
    adapter, source_id = smap[device]
    before = _dpi_get(adapter, source_id)
    hmon = _hmon_for_device(device)
    gdpi_before = _monitor_dpi(hmon) if hmon else None
    ok = _dpi_set(adapter, source_id, percent)
    time.sleep(1.0)
    after = _dpi_get(adapter, source_id)
    hmon2 = _hmon_for_device(device)
    gdpi_after = _monitor_dpi(hmon2) if hmon2 else None
    emit(
        "setdpi",
        device=device,
        percent=percent,
        set_ok=ok,
        ccd_before=before,
        ccd_after=after,
        getdpiformonitor_before=gdpi_before,
        getdpiformonitor_after=gdpi_after,
    )


# ---------------------------------------------------------------------------
# Q1/Q2/Q5 — parsec-vdd device control (ports nomi-san/parsec-vdd core header)
# ---------------------------------------------------------------------------

VDD_IOCTL_ADD = 0x0022E004
VDD_IOCTL_REMOVE = 0x0022A008
VDD_IOCTL_UPDATE = 0x0022A00C
VDD_IOCTL_VERSION = 0x0022E010

DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 0x00000003
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.POINTER(wintypes.ULONG)),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.POINTER(wintypes.ULONG)),
        ("InternalHigh", ctypes.POINTER(wintypes.ULONG)),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


def _vdd_guid() -> GUID:
    g = GUID()
    g.Data1 = 0x00B41627
    g.Data2 = 0x04C4
    g.Data3 = 0x429E
    for i, b in enumerate((0xA2, 0x6E, 0x02, 0x65, 0xCF, 0x50, 0xC8, 0xFA)):
        g.Data4[i] = b
    return g


def open_vdd() -> int | None:
    guid = _vdd_guid()
    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    hdev = setupapi.SetupDiGetClassDevsW(
        byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if hdev == INVALID_HANDLE_VALUE or hdev is None:
        return None
    try:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
        if not setupapi.SetupDiEnumDeviceInterfaces(
            ctypes.c_void_p(hdev), None, byref(guid), 0, byref(did)
        ):
            return None
        req = wintypes.DWORD(0)
        setupapi.SetupDiGetDeviceInterfaceDetailW(
            ctypes.c_void_p(hdev), byref(did), None, 0, byref(req), None
        )
        buf = ctypes.create_string_buffer(req.value)
        # SP_DEVICE_INTERFACE_DETAIL_DATA_W: cbSize (DWORD) + DevicePath (WCHAR[])
        cbsize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
        ctypes.memmove(buf, ctypes.byref(wintypes.DWORD(cbsize)), 4)
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(
            ctypes.c_void_p(hdev), byref(did), buf, req.value, None, None
        ):
            return None
        path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        handle = kernel32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_RW,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            emit("parsec_open", ok=False, path=path, err=ctypes.get_last_error())
            return None
        emit("parsec_open", ok=True, path=path)
        return handle
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(ctypes.c_void_p(hdev))


def vdd_ioctl(handle: int, code: int, in_buf: bytes = b"") -> int:
    out = wintypes.DWORD(0)
    ov = OVERLAPPED()
    ov.hEvent = kernel32.CreateEventW(None, False, False, None)
    inp = ctypes.create_string_buffer(in_buf, len(in_buf)) if in_buf else None
    returned = wintypes.DWORD(0)
    kernel32.DeviceIoControl(
        ctypes.c_void_p(handle),
        wintypes.DWORD(code),
        inp,
        len(in_buf),
        byref(out),
        ctypes.sizeof(out),
        byref(returned),
        byref(ov),
    )
    kernel32.WaitForSingleObject(ov.hEvent, 1000)
    kernel32.CloseHandle(ov.hEvent)
    return out.value


def vdd_version(handle: int) -> int:
    return vdd_ioctl(handle, VDD_IOCTL_VERSION) & 0xFFFF


def vdd_add(handle: int) -> int:
    idx = vdd_ioctl(handle, VDD_IOCTL_ADD)
    vdd_ioctl(handle, VDD_IOCTL_UPDATE)
    return idx & 0xFFFF


def vdd_remove(handle: int, index: int) -> None:
    swapped = ((index & 0xFF) << 8) | ((index >> 8) & 0xFF)
    vdd_ioctl(handle, VDD_IOCTL_REMOVE, swapped.to_bytes(2, "little"))
    vdd_ioctl(handle, VDD_IOCTL_UPDATE)


class Pinger(threading.Thread):
    def __init__(self, handle: int) -> None:
        super().__init__(daemon=True)
        self.handle = handle
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            vdd_ioctl(self.handle, VDD_IOCTL_UPDATE)
            self._stop.wait(0.2)

    def stop(self) -> None:
        self._stop.set()


def _parsec_devices() -> list[str]:
    r"""active \\.\DISPLAYn whose adapter DeviceString names Parsec."""
    names: list[str] = []
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(None, i, byref(dd), 0):
            break
        if "parsec" in dd.DeviceString.lower() and (dd.StateFlags & 0x1):
            names.append(dd.DeviceName)
        i += 1
    return names


def cmd_parsec_battery(count: int) -> int:
    marker("Q1 PARSEC OPEN DEVICE HANDLE")
    handle = open_vdd()
    if handle is None:
        marker("Q1 RESULT: FAIL — could not open parsec-vdd device (driver not installed?)")
        return 2
    ver = vdd_version(handle)
    emit("parsec_version", minor=ver)
    marker(f"Q1 RESULT: PASS — device handle open, driver reports version minor={ver}")

    pinger = Pinger(handle)
    pinger.start()

    marker(f"Q2 ADD {count} VIRTUAL DISPLAYS")
    added: list[int] = []
    for _ in range(count):
        idx = vdd_add(handle)
        added.append(idx)
        emit("parsec_add", index=idx)
        time.sleep(1.0)
    time.sleep(4.0)  # let Windows attach the monitors
    full_dump("after-parsec-add")
    parsec_devs = _parsec_devices()
    emit("parsec_devices", devices=parsec_devs, added_indices=added)
    marker(
        f"Q2 RESULT: {'PASS' if parsec_devs else 'FAIL'} — "
        f"{len(parsec_devs)} parsec monitor(s) enumerated: {parsec_devs}"
    )

    marker("Q3 SET DIFFERENT RESOLUTIONS PER VIRTUAL MONITOR")
    targets = [(1920, 1080), (2560, 1440), (1280, 720), (3840, 2160)]
    for dev, (w, h) in zip(parsec_devs, targets):
        set_resolution(dev, w, h)
    time.sleep(2.0)
    full_dump("after-setres")

    marker("Q4 LIVE PER-MONITOR DPI OVERRIDE")
    dpi_targets = [150, 200, 125, 175]
    for dev, pct in zip(parsec_devs, dpi_targets):
        set_dpi(dev, pct)
    full_dump("after-setdpi")

    marker("CLEANUP: remove virtual displays")
    for idx in added:
        vdd_remove(handle, idx)
    pinger.stop()
    time.sleep(2.0)
    full_dump("after-remove")
    kernel32.CloseHandle(ctypes.c_void_p(handle))
    return 0


def cmd_parsec_hold(count: int, seconds: int) -> int:
    handle = open_vdd()
    if handle is None:
        marker("PARSEC HOLD: FAIL — device not open")
        return 2
    pinger = Pinger(handle)
    pinger.start()
    added = []
    for _ in range(count):
        idx = vdd_add(handle)
        added.append(idx)
        time.sleep(1.0)
    time.sleep(4.0)
    emit("parsec_hold_ready", added=added, devices=_parsec_devices())
    full_dump("hold-ready")
    time.sleep(seconds)
    for idx in added:
        vdd_remove(handle, idx)
    pinger.stop()
    kernel32.CloseHandle(ctypes.c_void_p(handle))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    ctypes.windll.kernel32.SetLastError(0)
    set_dpi_aware()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("baseline")
    e = sub.add_parser("enumerate")
    e.add_argument("--tag", default="enumerate")
    sr = sub.add_parser("set-res")
    sr.add_argument("--device", required=True)
    sr.add_argument("--w", type=int, required=True)
    sr.add_argument("--h", type=int, required=True)
    sd = sub.add_parser("set-dpi")
    sd.add_argument("--device", required=True)
    sd.add_argument("--percent", type=int, required=True)
    pb = sub.add_parser("parsec-battery")
    pb.add_argument("--count", type=int, default=2)
    ph = sub.add_parser("parsec-hold")
    ph.add_argument("--count", type=int, default=2)
    ph.add_argument("--seconds", type=int, default=60)

    args = p.parse_args(argv)
    if args.cmd == "baseline":
        full_dump("baseline")
        return 0
    if args.cmd == "enumerate":
        full_dump(args.tag)
        return 0
    if args.cmd == "set-res":
        set_resolution(args.device, args.w, args.h)
        return 0
    if args.cmd == "set-dpi":
        set_dpi(args.device, args.percent)
        return 0
    if args.cmd == "parsec-battery":
        return cmd_parsec_battery(args.count)
    if args.cmd == "parsec-hold":
        return cmd_parsec_hold(args.count, args.seconds)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
