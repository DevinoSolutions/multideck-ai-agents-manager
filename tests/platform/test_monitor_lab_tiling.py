"""Monitor-lab tiling tier: REAL windows tiled across REAL virtual monitors at
mixed DPI, on a hosted ``windows-latest`` runner.

This is the live half of the multi-monitor coverage that DESIGN.md R4-05 left
open. It fabricates a mixed-DPI, multi-monitor topology with the parsec-vdd
virtual-display driver (see ``monitor_lab.py``), then drives multideck's real
``--go`` launch+tile pipeline and asserts -- in PHYSICAL pixels, across
monitors at different DPI scales -- that each real Windows Terminal window
lands inside the ``grid.compute_grid`` cell computed for its monitor.

CI-ONLY BY DESIGN -- like the ``needs_ssh`` tier, and for a harsher reason:
these tests INSTALL A KERNEL-ADJACENT DISPLAY DRIVER. They run ONLY when
``MDTEST_MONITOR_LAB=1`` (the ``monitor-lab`` CI job sets it on a throwaway
runner that is discarded at job end). NEVER set that variable or install
parsec-vdd on a real dev machine to run these locally -- without the variable
the whole module skips cleanly. The offline grid-math half lives in
``tests/unit/test_monitor_lab_topologies.py`` and runs everywhere.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.monitor_lab,
    pytest.mark.skipif(
        sys.platform != "win32", reason="virtual-monitor lab is win32-only"
    ),
    pytest.mark.skipif(
        os.environ.get("MDTEST_MONITOR_LAB") != "1",
        reason=(
            "monitor-lab tier installs the parsec-vdd display driver; CI-only "
            "(set MDTEST_MONITOR_LAB=1). Never enable on a dev machine."
        ),
    ),
]

# Pinned parsec-vdd release (WHQL-signed, silent /S install, no reboot).
_PARSEC_URL = (
    "https://github.com/nomi-san/parsec-vdd/releases/download/v0.45.1/"
    "ParsecVDisplay-v0.45-portable.zip"
)
_PARSEC_SHA256 = "9792e4121d85ed3e4c40c2d8ba36ec8657e13227a8357d719d923e801238ccdd"

_WM_CLOSE = 0x0010
_EDGE_TOL = 100  # px: window chrome / DPI rounding slack per edge
_MATERIALIZE_TIMEOUT = 90  # s: slow CI VMs are slow to paint wt windows

# The layout zoo: each entry is the list of virtual displays to add, as
# (width, height, dpi_percent). Positioned left-to-right by the lab; the
# runner's own (primary) monitor stays monitor 0.
ZOO: dict[str, list[tuple[int, int, int]]] = {
    "dual_mixed_dpi": [(1920, 1080, 100), (2560, 1440, 150)],
    "solo_4k": [(3840, 2160, 200)],
    "triple_720p": [(1280, 720, 125), (1280, 720, 125), (1280, 720, 125)],
}


# --------------------------------------------------------------------------- #
# driver install (session-scoped, in the fixture per the tier's contract)
# --------------------------------------------------------------------------- #


def _install_parsec_vdd(workdir: Path) -> None:
    zip_path = workdir / "parsec.zip"
    urllib.request.urlretrieve(_PARSEC_URL, zip_path)  # pinned https, sha256 below
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if digest != _PARSEC_SHA256:
        raise AssertionError(
            f"parsec-vdd zip sha256 mismatch: got {digest}, want {_PARSEC_SHA256}"
        )
    extract = workdir / "parsec"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract)
    installers = list(extract.rglob("parsec-vdd-*.exe"))
    if not installers:
        raise AssertionError("parsec-vdd installer not found in portable zip")
    proc = subprocess.run(
        [str(installers[0]), "/S"], capture_output=True, timeout=180, check=False
    )
    assert proc.returncode == 0, f"parsec-vdd silent install failed: {proc.returncode}"
    time.sleep(15)  # driver store settle (~15s once, per the spike)


@pytest.fixture(scope="session")
def lab(tmp_path_factory):
    """Install the driver, open the lab (handle + keep-alive pinger), yield the
    controller, and fully tear down (reset DPI, remove displays, close handle)
    even if a test explodes."""
    from .monitor_lab import MonitorLab, MonitorLabError

    workdir = tmp_path_factory.mktemp("parsec")
    _install_parsec_vdd(workdir)
    try:
        controller = MonitorLab().open()
    except MonitorLabError as exc:  # pragma: no cover - install/driver failure
        pytest.fail(f"could not open the virtual-display lab: {exc}")
    try:
        yield controller
    finally:
        controller.clear()
        _emit_events(controller, "session-teardown")


def _emit_events(controller, tag: str) -> None:
    """Surface the lab's structured event log as a CI ``::warning`` -- the lab
    never writes to stdout, so this is the one diagnostic channel."""
    if controller.events:
        joined = " | ".join(controller.events[-40:])
        print(f"::warning title=monitor-lab {tag}::{joined}")  # noqa: T201  # reason: GitHub Actions ::warning marker is the lab diagnostic channel


# --------------------------------------------------------------------------- #
# real-window helpers (physical rects via Win32, mirrors test_real_launch.py)
# --------------------------------------------------------------------------- #


@dataclass
class _Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def cx(self) -> float:
        return (self.left + self.right) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2


def _window_rect(hwnd) -> _Rect:
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = RECT()
    assert ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return _Rect(rect.left, rect.top, rect.right, rect.bottom)


def _child_env(home: Path) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.upper().startswith("MULTIDECK_")
    }
    home_s = str(home)
    drive, tail = os.path.splitdrive(home_s)
    env["USERPROFILE"] = home_s
    env["HOMEDRIVE"] = drive
    env["HOMEPATH"] = tail or "\\"
    env["HOME"] = home_s
    return env


def _wait_until(check, timeout: float, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() >= deadline:
            return result
        time.sleep(interval)


def _md_handles(plat, titles: list[str]) -> dict[str, object]:
    snap = plat.snapshot_windows()
    return {t: snap[t] for t in titles if t in snap}


def _cmd_procs_with(marker: str) -> list[int]:
    query = (
        "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
        "ForEach-Object { if ($_.CommandLine -like '*" + marker + "*') "
        "{ $_.ProcessId } } | ConvertTo-Json -Compress"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", query],
        capture_output=True,
        text=True,
        timeout=90,
    )
    out = (r.stdout or "").strip()
    if not out:
        return []
    data = json.loads(out)
    return [data] if isinstance(data, int) else list(data)


def _close_and_verify_gone(plat, titles: list[str], marker: str) -> list[str]:
    for hwnd in _md_handles(plat, titles).values():
        ctypes.windll.user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
    _wait_until(lambda: not _md_handles(plat, titles), timeout=15)
    for pid in _cmd_procs_with(marker):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
        )
    _wait_until(
        lambda: not _md_handles(plat, titles) and not _cmd_procs_with(marker),
        timeout=15,
    )
    leftovers = [f"window {t}" for t in _md_handles(plat, titles)]
    leftovers += [f"process pid={p}" for p in _cmd_procs_with(marker)]
    return leftovers


def _assert_in_slot(rect: _Rect, slot, label: str) -> None:
    assert abs(rect.left - slot.x) <= _EDGE_TOL, (
        f"{label}: left {rect.left} vs {slot.x}"
    )
    assert abs(rect.top - slot.y) <= _EDGE_TOL, f"{label}: top {rect.top} vs {slot.y}"
    assert abs(rect.right - (slot.x + slot.w)) <= _EDGE_TOL, (
        f"{label}: right {rect.right} vs {slot.x + slot.w}"
    )
    assert abs(rect.bottom - (slot.y + slot.h)) <= _EDGE_TOL, (
        f"{label}: bottom {rect.bottom} vs {slot.y + slot.h}"
    )
    assert slot.x <= rect.cx <= slot.x + slot.w, f"{label}: center_x outside its cell"
    assert slot.y <= rect.cy <= slot.y + slot.h, f"{label}: center_y outside its cell"


# --------------------------------------------------------------------------- #
# the zoo
# --------------------------------------------------------------------------- #


@pytest.fixture(params=list(ZOO), ids=list(ZOO))
def topology(request, lab):
    """Fresh virtual-display topology per zoo layout: clean slate, add this
    layout's displays, yield its specs, then reset back to the clean slate so
    the next parametrization starts from the runner's bare primary."""
    specs = ZOO[request.param]
    lab.reset_displays()
    for w, h, dpi in specs:
        lab.add(w, h, dpi)
    time.sleep(2.0)  # let the new topology settle before enumeration
    try:
        yield specs
    finally:
        lab.reset_displays()


def test_windows_tile_across_virtual_monitors(topology, lab, tmp_path):
    if shutil.which("wt") is None:
        pytest.skip("Windows Terminal (wt) not on PATH")

    specs = topology
    monitors = lab.snapshot()
    virtuals = [m for m in monitors if not m.is_primary]
    assert len(virtuals) >= len(specs), (
        f"expected >= {len(specs)} virtual monitor(s); lab view: "
        f"{lab.snapshot_json()} (events: {lab.events[-20:]})"
    )

    from multideck.grid import compute_grid
    from multideck.platform import get_platform

    plat = get_platform()
    plat.set_dpi_aware()

    # One slot per monitor (columns=rows=1): target i -> slots[i] -> monitor i,
    # so a window lands on every monitor including each virtual one.
    slots = compute_grid(monitors, 1, 1)
    monitors_sorted = sorted(monitors, key=lambda m: m.x)
    assert len(slots) == len(monitors_sorted)
    n = len(slots)

    # 1. Each added virtual monitor reports the resolution AND DPI we set,
    #    THROUGH multideck's own list_monitors() view -- the mixed-DPI
    #    precondition, in physical pixels. Virtuals are laid out left-to-right
    #    in add order, so virtuals[k] <-> specs[k].
    virtuals_sorted = sorted(virtuals, key=lambda m: m.x)
    for k, (w, _h, dpi) in enumerate(specs):
        vm = virtuals_sorted[k]
        assert vm.w == w, (
            f"virtual {k}: width {vm.w} != requested {w} (events: {lab.events[-12:]})"
        )
        assert round(vm.scale_factor * 100) == dpi, (
            f"virtual {k}: DPI {round(vm.scale_factor * 100)}% != {dpi}% "
            f"(events: {lab.events[-12:]})"
        )

    # 2. Launch one real wt window per monitor via the real --go pipeline.
    unique = uuid.uuid4().hex[:8]
    marker = f"mdml-{unique}"
    names = [f"mdml{unique}s{i}" for i in range(n)]
    titles = [f"md:{name}" for name in names]

    proj = tmp_path / f"proj-{unique}"
    proj.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    cfg = tmp_path / "multideck.config.json"
    cfg.write_text(
        json.dumps(
            {
                "version": 3,
                "layout": {"columns": 1, "rows": 1},
                "settings": {
                    "defaultTool": "probe",
                    "settleSeconds": 1,
                    "launchDelayMs": 400,
                    "psmux": False,
                    "uploadServer": False,
                    "tools": {"probe": f"rem {marker}"},
                },
                "projects": [
                    {
                        "path": str(proj),
                        "title": f"mdml{unique}",
                        "windows": [{"name": name} for name in names],
                    }
                ],
            }
        )
    )

    try:
        result = subprocess.run(
            [sys.executable, "-m", "multideck", "--go", "--config", str(cfg)],
            capture_output=True,
            text=True,
            timeout=300,
            env=_child_env(home),
        )
        assert result.returncode == 0, (
            f"--go failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

        handles = _wait_until(
            lambda: (h := _md_handles(plat, titles)) and len(h) == n and h,
            timeout=_MATERIALIZE_TIMEOUT,
        )
        assert handles, (
            f"expected {n} windows {titles}; visible md: windows: "
            f"{[t for t in plat.snapshot_windows() if t.startswith('md:')]}"
        )

        # 3. Each window i sits in slots[i], on monitor i -- physical pixels,
        #    mixed DPI. The virtual-monitor windows (i >= 1) are the payload.
        for i, title in enumerate(titles):
            _assert_in_slot(_window_rect(handles[title]), slots[i], f"window {i}")
            assert slots[i].monitor_index == i
    finally:
        leftovers = _close_and_verify_gone(plat, titles, marker)
        _emit_events(lab, f"after {'-'.join(str(s) for s in specs[0])}")
        assert not leftovers, f"cleanup left windows/processes behind: {leftovers}"
