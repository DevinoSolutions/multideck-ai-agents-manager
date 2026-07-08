"""CLI-level tests for `multideck attention` (cli/attention_cmd.py)."""

from __future__ import annotations

import json
import os
import time

from multideck import agent_state, cli, log
from multideck.cli import attention_cmd
from tests.conftest import FakePlatform


class TestStop:
    def test_stop_when_not_running_says_so(self, runner, monkeypatch, tmp_path):
        monkeypatch.setattr(attention_cmd, "_PID_PATH", tmp_path / "attention.pid")

        result = runner.invoke(cli.main, ["attention", "--stop"])

        assert result.exit_code == 0
        assert "not running" in result.output

    def test_stale_pid_file_is_cleared(self, monkeypatch, tmp_path):
        pid_file = tmp_path / "attention.pid"
        pid_file.write_text("999999999")  # nothing plausible alive at this pid
        monkeypatch.setattr(attention_cmd, "_PID_PATH", pid_file)

        assert attention_cmd.daemon_pid() is None
        assert not pid_file.exists()


class TestDaemonFlag:
    def test_daemon_reports_already_running(self, runner, monkeypatch, tmp_path):
        pid_file = tmp_path / "attention.pid"
        pid_file.write_text(str(os.getpid()))  # this test process is alive
        monkeypatch.setattr(attention_cmd, "_PID_PATH", pid_file)

        result = runner.invoke(cli.main, ["attention", "--daemon"])

        assert result.exit_code == 0
        assert "already running" in result.output


class TestForeground:
    def test_one_tick_badges_heartbeats_and_clears_pid(
        self, runner, monkeypatch, tmp_path, tmp_config
    ):
        proj_dir = tmp_path / "api"
        proj_dir.mkdir()
        state_dir = tmp_path / "state"
        monkeypatch.setattr(agent_state, "STATE_DIR", state_dir)
        agent_state.write_state(str(proj_dir), agent_state.NEEDS_INPUT)

        fp = FakePlatform(windows={"md:api": 1}, supports_attention=True)
        monkeypatch.setattr("multideck.platform.get_platform", lambda: fp)
        pid_file = tmp_path / "attention.pid"
        monkeypatch.setattr(attention_cmd, "_PID_PATH", pid_file)

        config_path = tmp_config({"version": 2, "projects": [{"path": str(proj_dir)}]})
        result = runner.invoke(
            cli.main, ["--config", config_path, "attention", "--ticks", "1"]
        )

        assert result.exit_code == 0, result.output
        # Badge on the tick, then stripped back to a clean title when the loop
        # ends — inverse-transience on daemon stop (P6-06).
        assert fp.titles_set == [(1, "md:[!] api"), (1, "md:api")]
        assert log.heartbeat_age(attention_cmd.HEARTBEAT_NAME) is not None
        assert not pid_file.exists()  # cleaned up on exit

    def test_daemon_start_ages_out_stale_records(
        self, runner, monkeypatch, tmp_path, tmp_config
    ):
        # P6-04: the daemon sweeps records past the retention TTL on start.
        proj_dir = tmp_path / "api"
        proj_dir.mkdir()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        monkeypatch.setattr(agent_state, "STATE_DIR", state_dir)
        monkeypatch.setattr(agent_state, "_swept_this_process", False)
        # a dead session long past the TTL (its end-hook never fired) ...
        old_cwd = "/gone/project"
        old_file = state_dir / f"{agent_state._key(old_cwd)}.json"
        old_file.write_text(
            json.dumps(
                {
                    "state": agent_state.DONE,
                    "ts": time.time() - agent_state.STATE_TTL_S - 100,
                    "cwd": agent_state.norm_cwd(old_cwd),
                }
            ),
            encoding="utf-8",
        )
        # ... plus a fresh record that must survive
        agent_state.write_state(str(proj_dir), agent_state.NEEDS_INPUT)

        fp = FakePlatform(windows={"md:api": 1}, supports_attention=True)
        monkeypatch.setattr("multideck.platform.get_platform", lambda: fp)
        monkeypatch.setattr(attention_cmd, "_PID_PATH", tmp_path / "attention.pid")

        config_path = tmp_config({"version": 2, "projects": [{"path": str(proj_dir)}]})
        result = runner.invoke(
            cli.main, ["--config", config_path, "attention", "--ticks", "1"]
        )

        assert result.exit_code == 0, result.output
        assert not old_file.exists()  # aged out on daemon start
        assert agent_state.state_for(str(proj_dir)) is not None  # fresh survives

    def test_unsupported_platform_with_only_ambient_renderers_exits_1(
        self, runner, monkeypatch, tmp_path, tmp_config
    ):
        fp = FakePlatform()  # supports_attention_signals() -> False
        monkeypatch.setattr("multideck.platform.get_platform", lambda: fp)
        monkeypatch.setattr(attention_cmd, "_PID_PATH", tmp_path / "attention.pid")

        config_path = tmp_config({"version": 2, "projects": [{"path": "api"}]})
        result = runner.invoke(
            cli.main, ["--config", config_path, "attention", "--ticks", "1"]
        )

        assert result.exit_code == 1
        assert "nothing to do" in result.output


class TestDaemonPrereqValidation:
    """P2-02: the `-d` parent validates renderer prerequisites on the STILL-
    ATTACHED console before detaching -- so the real reason is visible and no
    detached child is spawned only to fail invisibly."""

    def test_no_renderers_fails_fast_without_spawning(
        self, runner, monkeypatch, tmp_path, tmp_config
    ):
        fp = FakePlatform()  # supports_attention_signals() -> False
        monkeypatch.setattr("multideck.platform.get_platform", lambda: fp)
        monkeypatch.setattr(attention_cmd, "_PID_PATH", tmp_path / "attention.pid")
        spawned: list = []
        monkeypatch.setattr("multideck.launch.spawn_detached", spawned.append)

        config_path = tmp_config({"version": 2, "projects": [{"path": "api"}]})
        result = runner.invoke(
            cli.main, ["--config", config_path, "attention", "--daemon"]
        )

        assert result.exit_code == 1
        assert "nothing to do" in result.output
        assert spawned == []  # the parent never detached a doomed child

    def test_valid_renderer_spawns(self, runner, monkeypatch, tmp_path, tmp_config):
        fp = FakePlatform(supports_attention=True)  # badge/flash enabled & supported
        monkeypatch.setattr("multideck.platform.get_platform", lambda: fp)
        pid_file = tmp_path / "attention.pid"
        monkeypatch.setattr(attention_cmd, "_PID_PATH", pid_file)

        def fake_spawn(args):
            pid_file.write_text(str(os.getpid()))  # simulate the child registering

        monkeypatch.setattr("multideck.launch.spawn_detached", fake_spawn)

        config_path = tmp_config({"version": 2, "projects": [{"path": "api"}]})
        result = runner.invoke(
            cli.main, ["--config", config_path, "attention", "--daemon"]
        )

        assert result.exit_code == 0, result.output
        assert "running" in result.output


class TestHeartbeatLifecycle:
    """P6-01: a clean stop removes the heartbeat file (status -> 'off'); a crash
    leaves it behind as the marker that makes status read 'crashed'."""

    def _run_foreground(self, runner, monkeypatch, tmp_path, tmp_config, loop):
        fp = FakePlatform(supports_attention=True)
        monkeypatch.setattr("multideck.platform.get_platform", lambda: fp)
        monkeypatch.setattr(attention_cmd, "_PID_PATH", tmp_path / "attention.pid")
        monkeypatch.setattr("multideck.attention.run_attention_loop", loop)
        config_path = tmp_config({"version": 2, "projects": [{"path": "api"}]})
        return runner.invoke(cli.main, ["--config", config_path, "attention"])

    def test_keyboard_interrupt_clears_heartbeat(
        self, runner, monkeypatch, tmp_path, tmp_config
    ):
        def loop(*_a, **_k):
            raise KeyboardInterrupt

        result = self._run_foreground(runner, monkeypatch, tmp_path, tmp_config, loop)

        assert result.exit_code == 0
        assert log.heartbeat_age(attention_cmd.HEARTBEAT_NAME) is None  # cleared

    def test_crash_leaves_heartbeat_as_marker(
        self, runner, monkeypatch, tmp_path, tmp_config
    ):
        def loop(*_a, **_k):
            raise RuntimeError("boom")

        result = self._run_foreground(runner, monkeypatch, tmp_path, tmp_config, loop)

        assert result.exit_code == 1  # the crash propagates out
        # heartbeat survives -> _attention_state() reads 'crashed', not 'off'
        assert log.heartbeat_age(attention_cmd.HEARTBEAT_NAME) is not None


class TestStopDaemonClearsHeartbeat:
    """P6-01: a confirmed kill via stop_daemon also clears the heartbeat, so
    `attention --stop` / `down --all` leave status reading 'off', not 'crashed'
    (a forced kill can't run the daemon's own cleanup)."""

    def test_successful_stop_removes_heartbeat(self, monkeypatch, tmp_path):
        pid_file = tmp_path / "attention.pid"
        pid_file.write_text("4321")
        monkeypatch.setattr(attention_cmd, "_PID_PATH", pid_file)
        # pid 4321 is "alive" until killed, then gone.
        alive = {4321}
        monkeypatch.setattr(attention_cmd, "pid_alive", lambda pid: pid in alive)
        monkeypatch.setattr(attention_cmd.sys, "platform", "win32")

        class _Result:
            returncode = 0

        def _kill(*_a, **_k):
            alive.discard(4321)
            return _Result()

        monkeypatch.setattr(attention_cmd.subprocess, "run", _kill)
        log.write_heartbeat(attention_cmd.HEARTBEAT_NAME)
        assert log.heartbeat_age(attention_cmd.HEARTBEAT_NAME) is not None

        assert attention_cmd.stop_daemon() is True
        assert log.heartbeat_age(attention_cmd.HEARTBEAT_NAME) is None
