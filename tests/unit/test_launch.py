"""Unit tests for multideck.launch.run_multideck's no-monitors error path
(F-D2-003 / F-D2-001: there was previously no test_launch.py at all).

Cross-platform: FakePlatform (tests/conftest.py) stands in for a real
Platform, so this exercises launch.py's `-> int` return-code contract without
touching any OS-specific window/monitor API.
"""
from __future__ import annotations

import time

import pytest

from tests.conftest import FakePlatform

from multideck.config import MultideckConfig, ProjectConfig, Settings
from multideck.grid import MonitorRect, Rect, compute_grid
from multideck.launch import RunOpts, _Target, _tile_targets, run_multideck


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


@pytest.fixture
def fake_sleep(monkeypatch):
    """Patches the real time.sleep function object -- launch.py's per-window
    launch_delay_ms sleep and tiling.py's retry-loop sleeps both do a
    module-level `import time`, so they share sys.modules['time'] and this
    one patch intercepts both (same convention as tests/unit/test_tiling.py's
    fake_sleep). Records each sleep's duration."""
    calls: list[float] = []

    def _sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(time, "sleep", _sleep)
    return calls


class TestRunMultideckCharacterization:
    """Whole-function behavior pins for run_multideck (R4), written BEFORE
    the phase extraction so every later extraction step is judged against
    locked behavior. Each test drives run_multideck directly (not through
    the CLI) and asserts on the fake_platform double's call record -- never
    on full-output equality (style/spacing may drift)."""

    def test_happy_local_cli_agent_launches_then_tiles(self, fake_platform, tmp_path, fake_sleep):
        cfg = MultideckConfig(
            projects=[ProjectConfig(path=str(tmp_path), tool="claude", title="proj")],
            settings=Settings(tools={"claude": "claude --continue"}, default_tool="claude"),
        )

        rc = run_multideck(cfg, RunOpts())

        assert rc == 0
        assert len(fake_platform.launched_terminals) == 1
        assert fake_platform.launched_terminals[0].title == "proj"
        assert len(fake_platform.moved) == 1
        assert fake_platform.moved[0][1] == Rect(x=0, y=0, w=960, h=1080)

    def test_dry_run_launches_and_moves_nothing(self, fake_platform, tmp_path, fake_sleep, capsys):
        cfg = MultideckConfig(
            projects=[ProjectConfig(path=str(tmp_path), tool="claude", title="proj")],
            settings=Settings(tools={"claude": "claude --continue"}, default_tool="claude"),
        )

        rc = run_multideck(cfg, RunOpts(dry_run=True))

        assert rc == 0
        assert fake_platform.launched_terminals == []
        assert fake_platform.launched_vscode == []
        assert fake_platform.moved == []
        assert "DRY RUN" in capsys.readouterr().out

    def test_ide_project_launches_vscode(self, fake_platform, tmp_path, fake_sleep):
        cfg = MultideckConfig(
            projects=[ProjectConfig(path=str(tmp_path), tool="code")],
            settings=Settings(tools={"claude": "claude --continue"}, default_tool="claude"),
        )

        rc = run_multideck(cfg, RunOpts())

        assert rc == 0
        assert len(fake_platform.launched_vscode) == 1
        assert fake_platform.launched_vscode[0].command == "code"

    def test_psmux_path_collects_and_attaches(self, monkeypatch, tmp_path, fake_sleep):
        fp = FakePlatform(supports_psmux=True)
        monkeypatch.setattr("multideck.launch.get_platform", lambda: fp)
        cfg = MultideckConfig(
            projects=[ProjectConfig(path=str(tmp_path), tool="claude", title="proj")],
            settings=Settings(tools={"claude": "claude --continue"}, default_tool="claude", psmux=True),
        )

        rc = run_multideck(cfg, RunOpts())

        assert rc == 0
        assert len(fp.launched_psmux) == 1
        assert len(fp.attached_psmux) == 1
        assert fp.launched_terminals == []

    def test_empty_group_returns_zero(self, fake_platform, tmp_path, fake_sleep, capsys):
        cfg = MultideckConfig(
            projects=[ProjectConfig(path=str(tmp_path), tool="claude", title="proj")],
            settings=Settings(tools={"claude": "claude --continue"}, default_tool="claude"),
        )

        rc = run_multideck(cfg, RunOpts(group="nope"))

        assert rc == 0
        assert fake_platform.launched_terminals == []
        assert "No projects in group" in capsys.readouterr().err

    def test_retile_all_places_running_window(self, monkeypatch, tmp_path, fake_sleep):
        fp = FakePlatform(windows={"proj": 555})
        monkeypatch.setattr("multideck.launch.get_platform", lambda: fp)
        cfg = MultideckConfig(
            projects=[ProjectConfig(path=str(tmp_path), tool="claude", title="proj")],
            settings=Settings(tools={"claude": "claude --continue"}, default_tool="claude"),
        )

        rc = run_multideck(cfg, RunOpts(retile_all=True))

        assert rc == 0
        assert fp.launched_terminals == []
        assert (555, Rect(x=0, y=0, w=960, h=1080)) in fp.moved


class TestTileTargets:
    """Direct unit test for the extracted tile phase (R4, Step 2)."""

    def test_moves_present_and_reports_missing(self, fake_sleep, capsys):
        fp = FakePlatform(windows={"present": 42})
        slots = compute_grid(
            [MonitorRect(x=0, y=0, w=1920, h=1080, is_primary=True, scale_factor=1.0)], 2, 1
        )
        targets = [
            _Target(name="present", key="present", mode="exact", is_new=True),
            _Target(name="absent", key="absent", mode="exact", is_new=True),
        ]

        _tile_targets(fp, RunOpts(), slots, targets)

        assert len(fp.moved) == 1
        assert fp.moved[0] == (42, Rect(x=0, y=0, w=960, h=1080))
        assert "not found" in capsys.readouterr().out
