import json
import subprocess
import sys

import pytest

pytestmark = pytest.mark.e2e


def _write_cfg(tmp_path, projects, settings=None):
    cfg = tmp_path / "multideck.config.json"
    data = {"projects": projects}
    if settings:
        data["settings"] = settings
    cfg.write_text(json.dumps(data))
    return cfg


def _run(cfg, *args):
    return subprocess.run(
        [sys.executable, "-m", "multideck", "--config", str(cfg), *args],
        capture_output=True, text=True,
    )


class TestUpJson:
    def test_lists_eligible_only(self, tmp_path):
        for name in ("api", "web", "docs"):
            (tmp_path / name).mkdir()
        cfg = _write_cfg(tmp_path, [
            {"path": str(tmp_path / "api"), "tool": "claude"},
            {"path": str(tmp_path / "web"), "tool": "codex"},
            {"path": str(tmp_path / "docs"), "tool": "vscode"},          # IDE -> excluded
            {"path": str(tmp_path / "api"), "tool": "claude", "host": "u@box"},  # remote -> excluded
        ], settings={"uploadPort": 9091})
        r = _run(cfg, "up", "--json")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout.strip().splitlines()[-1])
        assert sorted(p["name"] for p in data["projects"]) == ["api", "web"]
        assert data["up"] == []
        assert sorted(d["name"] for d in data["down"]) == ["api", "web"]
        assert data["uploadPort"] == 9091
        # eligible entries carry the launch command used to create the session
        api = next(p for p in data["projects"] if p["name"] == "api")
        assert api["cmd"] == "claude --continue"

    def test_bad_config_errors_as_json(self, tmp_path):
        cfg = tmp_path / "bad.json"
        cfg.write_text("not json{")
        r = _run(cfg, "up", "--json")
        assert r.returncode != 0
        assert "error" in r.stdout.lower()

    def test_group_filter(self, tmp_path):
        for name in ("a", "b", "c"):
            (tmp_path / name).mkdir()
        cfg = _write_cfg(tmp_path, [
            {"path": str(tmp_path / "a"), "tool": "claude", "group": "X"},
            {"path": str(tmp_path / "b"), "tool": "claude", "group": "Y"},
            {"path": str(tmp_path / "c"), "tool": "claude", "group": "X"},
        ])
        r = _run(cfg, "up", "--json", "-g", "X")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout.strip().splitlines()[-1])
        assert sorted(p["name"] for p in data["projects"]) == ["a", "c"]
        assert all(p["group"] == "X" for p in data["projects"])


class TestAttachHelp:
    def test_attach_registered(self):
        r = subprocess.run(
            [sys.executable, "-m", "multideck", "attach", "--help"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert "--no-mux" in r.stdout
