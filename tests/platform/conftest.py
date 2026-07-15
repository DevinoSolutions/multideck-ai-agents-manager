"""Shared fixtures for the live monitor-lab tier.

The ``lab`` fixture is session-scoped so BOTH monitor-lab test modules
(``test_monitor_lab_tiling.py`` and ``test_doctor_replay.py``) share ONE
parsec-vdd driver install and ONE open lab for the whole CI job -- the tier's
one-install contract. It is only ever instantiated on a gated win32 runner
(every monitor-lab test carries ``lab_harness.PYTESTMARK``); on any other OS or
without ``MDTEST_MONITOR_LAB=1`` those tests skip and this fixture never runs,
so the driver is never installed on a dev box.

Import-harmless on POSIX: only ``lab_harness`` and ``pytest`` are imported at
module scope, and the win32-only lab engine is imported lazily in the fixture
body.
"""

from __future__ import annotations

import pytest

from . import lab_harness


@pytest.fixture(scope="session")
def lab(tmp_path_factory):
    """Install the driver, open the lab (handle + keep-alive pinger), yield the
    controller, and fully tear down (reset DPI, remove displays, close handle)
    even if a test explodes."""
    from .monitor_lab import MonitorLab, MonitorLabError

    workdir = tmp_path_factory.mktemp("parsec")
    lab_harness.install_parsec_vdd(workdir)
    try:
        controller = MonitorLab().open()
    except MonitorLabError as exc:  # pragma: no cover - install/driver failure
        pytest.fail(f"could not open the virtual-display lab: {exc}")
    try:
        yield controller
    finally:
        controller.clear()
        lab_harness.emit_events(controller, "session-teardown")
