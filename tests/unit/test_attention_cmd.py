"""CLI-level tests for `multideck attention` (cli/attention_cmd.py)."""

from __future__ import annotations

import os

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
        assert fp.titles_set == [(1, "md:[!] api")]
        assert log.heartbeat_age(attention_cmd.HEARTBEAT_NAME) is not None
        assert not pid_file.exists()  # cleaned up on exit

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
