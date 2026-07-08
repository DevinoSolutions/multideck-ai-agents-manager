"""Unit tests for `multideck status` -- real liveness (HTTP /health + hook
heartbeat) instead of presence-only port/pid probes (F-IC-005), plus the new
degraded exit code and --json (R2's status half).

End-to-end through status_cmd via click.testing.CliRunner. psmux_status is
monkeypatched to avoid touching real psmux; an explicit --config <path> (like
test_up_json / test_main_dry_run_dispatch in test_cli_smoke.py) sidesteps
config *discovery* entirely, so no test ever searches the real filesystem.
"""

from __future__ import annotations

import json
import sys

from multideck import cli


def _no_psmux(monkeypatch):
    monkeypatch.setattr(
        "multideck.launch.psmux_status", lambda cfg, group=None: ([], [], [])
    )


def _both_off(monkeypatch):
    """Baseline: upload server unreachable/absent, listener not running."""
    monkeypatch.setattr("multideck.cli.status._health_check", lambda port: False)
    monkeypatch.setattr("multideck.cli.status._probe_port", lambda port: False)
    monkeypatch.setattr("multideck.upload_server.server_pid", lambda port: None)
    monkeypatch.setattr("multideck.cli.status.pid_alive", lambda pid: False)
    if sys.platform == "win32":
        monkeypatch.setattr("multideck.hotkey.listener_pid", lambda: None)
    else:
        monkeypatch.setattr("multideck.cli.status._listener_state", lambda: "off")


class TestNoConfig:
    """Pin: preserved from before the liveness-probe change."""

    def test_exit_1_when_no_config(self, runner, tmp_path):
        result = runner.invoke(
            cli.main, ["--config", str(tmp_path / "nope.json"), "status"]
        )
        assert result.exit_code == 1

    def test_json_exit_1_when_no_config(self, runner, tmp_path):
        result = runner.invoke(
            cli.main, ["--config", str(tmp_path / "nope.json"), "status", "--json"]
        )
        assert result.exit_code == 1
        assert json.loads(result.output) == {"error": "No config found."}


class TestStatusLines:
    def test_prints_upload_server_and_listener_lines(
        self, runner, tmp_config, monkeypatch
    ):
        # Pin: the report's two daemon lines are the status contract,
        # independent of the liveness probes' actual state.
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert "Upload server" in result.output
        assert "Alt+V listener" in result.output

    def test_both_off_is_healthy_exit_0(self, runner, tmp_config, monkeypatch):
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 0
        assert "off" in result.output


class TestUploadServerLiveness:
    def test_health_check_true_means_on_exit_0(self, runner, tmp_config, monkeypatch):
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        monkeypatch.setattr("multideck.cli.status._health_check", lambda port: True)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 0
        assert "ON" in result.output

    def test_health_false_but_port_open_means_dead_exit_3(
        self, runner, tmp_config, monkeypatch
    ):
        # The exact "reports ON while dead" bug (F-IC-005), now surfaced.
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        monkeypatch.setattr("multideck.cli.status._probe_port", lambda port: True)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 3
        assert "DEAD" in result.output

    def test_health_false_but_pid_alive_means_dead_exit_3(
        self, runner, tmp_config, monkeypatch
    ):
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        monkeypatch.setattr("multideck.upload_server.server_pid", lambda port: 4321)
        monkeypatch.setattr("multideck.cli.status.pid_alive", lambda pid: pid == 4321)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 3
        assert "DEAD" in result.output


class TestListenerLiveness:
    def test_heartbeat_not_fresh_with_live_pid_means_stale_exit_3(
        self, runner, tmp_config, monkeypatch
    ):
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        monkeypatch.setattr(
            "multideck.cli.status._health_check", lambda port: True
        )  # upload healthy
        if sys.platform == "win32":
            monkeypatch.setattr("multideck.hotkey.listener_pid", lambda: 9999)
            monkeypatch.setattr(
                "multideck.cli.status.heartbeat_fresh", lambda name: False
            )
        else:
            monkeypatch.setattr("multideck.cli.status._listener_state", lambda: "stale")
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 3
        assert "STALE" in result.output


class TestJson:
    def test_healthy_emits_parseable_status_and_exit_0(
        self, runner, tmp_config, monkeypatch
    ):
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        monkeypatch.setattr("multideck.cli.status._health_check", lambda port: True)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout) == {
            "upload_server": "on",
            "listener": "off",
            "attention": "off",
            "agents": [],
        }

    def test_degraded_emits_parseable_status_and_exit_3(
        self, runner, tmp_config, monkeypatch
    ):
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)
        monkeypatch.setattr(
            "multideck.cli.status._probe_port", lambda port: True
        )  # -> dead
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status", "--json"])

        assert result.exit_code == 3
        assert json.loads(result.stdout) == {
            "upload_server": "dead",
            "listener": "off",
            "attention": "off",
            "agents": [],
        }


class TestAttentionLiveness:
    """P6-01: a crashed attention daemon -- a heartbeat file left behind with no
    live pid -- must read 'crashed' and degrade the exit code, distinct from a
    clean 'off' (never started / cleanly stopped, which removes the heartbeat)."""

    def _attention(self, monkeypatch, *, pid, fresh, age):
        _no_psmux(monkeypatch)
        _both_off(monkeypatch)  # upload + listener both healthy-off
        monkeypatch.setattr("multideck.cli.attention_cmd.daemon_pid", lambda: pid)
        monkeypatch.setattr("multideck.cli.status.heartbeat_fresh", lambda name: fresh)
        monkeypatch.setattr("multideck.cli.status.heartbeat_age", lambda name: age)

    def test_pid_and_fresh_heartbeat_is_on_exit_0(
        self, runner, tmp_config, monkeypatch
    ):
        self._attention(monkeypatch, pid=4242, fresh=True, age=1.0)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 0
        assert "Attention" in result.output
        assert "CRASHED" not in result.output

    def test_pid_but_stale_heartbeat_is_stale_exit_3(
        self, runner, tmp_config, monkeypatch
    ):
        self._attention(monkeypatch, pid=4242, fresh=False, age=999.0)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 3
        assert "STALE" in result.output

    def test_no_pid_with_lingering_heartbeat_is_crashed_exit_3(
        self, runner, tmp_config, monkeypatch
    ):
        self._attention(monkeypatch, pid=None, fresh=False, age=12.0)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 3
        assert "CRASHED" in result.output

    def test_no_pid_no_heartbeat_is_off_exit_0(self, runner, tmp_config, monkeypatch):
        self._attention(monkeypatch, pid=None, fresh=False, age=None)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status"])

        assert result.exit_code == 0
        assert "CRASHED" not in result.output
        assert "STALE" not in result.output

    def test_json_crashed_degrades_exit_3(self, runner, tmp_config, monkeypatch):
        self._attention(monkeypatch, pid=None, fresh=False, age=8.0)
        cfgpath = tmp_config({"projects": []})

        result = runner.invoke(cli.main, ["--config", cfgpath, "status", "--json"])

        assert result.exit_code == 3
        assert json.loads(result.stdout)["attention"] == "crashed"
