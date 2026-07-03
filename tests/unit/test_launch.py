"""Unit tests for multideck.launch.run_multideck's no-monitors error path
(F-D2-003 / F-D2-001: there was previously no test_launch.py at all).

Cross-platform: FakePlatform (tests/conftest.py) stands in for a real
Platform, so this exercises launch.py's `-> int` return-code contract without
touching any OS-specific window/monitor API.
"""
from __future__ import annotations

from tests.conftest import FakePlatform

from multideck.config import MultideckConfig
from multideck.launch import RunOpts, run_multideck


class TestNoMonitors:
    def test_returns_2_and_logs_error(self, monkeypatch, caplog):
        # FakePlatform's list_monitors() needs only monitors=[] and a no-op
        # set_dpi_aware() -- the no-monitors guard returns before
        # snapshot_windows or anything else on Platform is touched.
        fp = FakePlatform(monitors=[])
        monkeypatch.setattr("multideck.launch.get_platform", lambda: fp)
        cfg = MultideckConfig(projects=[])

        with caplog.at_level("ERROR", logger="multideck.launch"):
            rc = run_multideck(cfg, RunOpts())

        assert rc == 2
        assert "no monitors detected" in caplog.text
        assert fp.dpi_aware_calls == 1  # set_dpi_aware still runs before the check
