import json
import pytest
from multideck.config import load_config, MultideckConfig, ProjectConfig


class TestLoadConfig:
    def test_minimal_valid_config(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api"}]})
        cfg = load_config(path)
        assert isinstance(cfg, MultideckConfig)
        assert len(cfg.projects) == 1
        assert cfg.projects[0].path == "api"

    def test_full_config(self, tmp_config):
        path = tmp_config({
            "baseDir": "C:/code",
            "layout": {"columns": 3, "rows": 2},
            "settings": {
                "defaultTool": "codex",
                "settleSeconds": 5,
                "launchDelayMs": 200,
                "ssh": {"shell": "zsh -lc"},
                "tools": {"claude": "claude --continue", "codex": "codex --yolo"},
            },
            "projects": [
                {"path": "api", "group": "backend", "color": "#ff0000",
                 "tool": "claude", "title": "my-api", "enabled": True,
                 "host": None, "remotePath": None, "windows": 3},
            ],
        })
        cfg = load_config(path)
        assert cfg.base_dir == "C:/code"
        assert cfg.layout.columns == 3
        assert cfg.layout.rows == 2
        assert cfg.settings.default_tool == "codex"
        assert cfg.settings.settle_seconds == 5
        assert cfg.settings.launch_delay_ms == 200
        assert cfg.settings.ssh.shell == "zsh -lc"
        assert cfg.settings.tools["codex"] == "codex --yolo"
        p = cfg.projects[0]
        assert p.group == "backend"
        assert p.color == "#ff0000"
        assert p.windows == 3

    def test_defaults_applied(self, tmp_config):
        path = tmp_config({"projects": [{"path": "x"}]})
        cfg = load_config(path)
        assert cfg.base_dir is None
        assert cfg.layout.columns == 2
        assert cfg.layout.rows == 1
        assert cfg.settings.default_tool == "claude"
        assert cfg.settings.settle_seconds == 3
        assert cfg.settings.launch_delay_ms == 400
        assert cfg.settings.ssh.shell == "bash -lc"
        assert "claude" in cfg.settings.tools

    def test_windows_as_string_array(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api", "windows": ["feat", "bugs"]}]})
        cfg = load_config(path)
        assert cfg.projects[0].windows == ["feat", "bugs"]

    def test_windows_omitted_is_none(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api"}]})
        cfg = load_config(path)
        assert cfg.projects[0].windows is None

    def test_enabled_defaults_true(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api"}]})
        cfg = load_config(path)
        assert cfg.projects[0].enabled is True

    def test_enabled_false(self, tmp_config):
        path = tmp_config({"projects": [{"path": "api", "enabled": False}]})
        cfg = load_config(path)
        assert cfg.projects[0].enabled is False

    def test_missing_projects_raises(self, tmp_config):
        path = tmp_config({"layout": {"columns": 2}})
        with pytest.raises(ValueError, match="projects"):
            load_config(path)

    def test_project_missing_path_raises(self, tmp_config):
        path = tmp_config({"projects": [{"group": "x"}]})
        with pytest.raises(ValueError, match="path"):
            load_config(path)

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json{{{")
        with pytest.raises(ValueError, match="valid JSON"):
            load_config(str(p))

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.json")


class TestPathResolution:
    def test_resolve_relative(self, tmp_config):
        path = tmp_config({
            "baseDir": "/home/user/code",
            "projects": [{"path": "api"}],
        })
        cfg = load_config(path)
        assert cfg.projects[0].path == "api"

    def test_resolve_absolute(self, tmp_config):
        path = tmp_config({"projects": [{"path": "/absolute/path"}]})
        cfg = load_config(path)
        assert cfg.projects[0].path == "/absolute/path"


from multideck.init_config import scan_for_projects, generate_config


class TestScanForProjects:
    def test_finds_git_repos(self, tmp_path):
        (tmp_path / "api" / ".git").mkdir(parents=True)
        (tmp_path / "web" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        paths = [r["path"] for r in repos]
        assert "api" in paths
        assert "web" in paths

    def test_finds_nested_repos(self, tmp_path):
        (tmp_path / "internal" / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        assert any(r["path"] == "internal/api" for r in repos)

    def test_adds_group_from_parent_folder(self, tmp_path):
        (tmp_path / "backend" / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        proj = [r for r in repos if r["path"] == "backend/api"][0]
        assert proj["group"] == "backend"

    def test_no_group_for_top_level(self, tmp_path):
        (tmp_path / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        proj = [r for r in repos if r["path"] == "api"][0]
        assert "group" not in proj

    def test_duplicate_leaf_gets_unique_title(self, tmp_path):
        (tmp_path / "frontend" / "api" / ".git").mkdir(parents=True)
        (tmp_path / "backend" / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        api_repos = [r for r in repos if r["path"].endswith("api")]
        titles = [r.get("title") for r in api_repos]
        assert all(t is not None for t in titles)
        assert len(set(titles)) == 2

    def test_skips_node_modules(self, tmp_path):
        (tmp_path / "node_modules" / "pkg" / ".git").mkdir(parents=True)
        (tmp_path / "api" / ".git").mkdir(parents=True)
        repos = scan_for_projects(str(tmp_path))
        assert len(repos) == 1

    def test_fallback_to_subdirectories(self, tmp_path):
        (tmp_path / "api").mkdir()
        (tmp_path / "web").mkdir()
        repos = scan_for_projects(str(tmp_path))
        assert len(repos) == 2


class TestGenerateConfig:
    def test_generates_valid_config(self, tmp_path):
        (tmp_path / "api" / ".git").mkdir(parents=True)
        (tmp_path / "web" / ".git").mkdir(parents=True)
        config = generate_config(str(tmp_path))
        assert config["baseDir"] == str(tmp_path).replace("\\", "/")
        assert len(config["projects"]) == 2
        assert config["layout"]["columns"] == 2
        assert config["settings"]["defaultTool"] == "claude"
