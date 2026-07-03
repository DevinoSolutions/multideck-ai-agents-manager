from __future__ import annotations

import json
from pathlib import Path

import pytest

from multideck.config import (
    DEFAULT_TOOLS,
    ConfigError,
    LayoutConfig,
    Settings,
    SCHEMA_VERSION,
    _parse_settings,
    default_config,
    layout_to_dict,
    load_config,
    migrate_config_file,
    settings_to_dict,
)
from multideck.discover import projects_to_config
from multideck.init_config import generate_config

EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "multideck.config.example.json"


class TestFactoryRoundtrip:
    def test_factory_roundtrip(self):
        # Anti-drift pin (R9): settings_to_dict and _parse_settings sit on
        # the same Settings dataclass, so a round-trip must be lossless.
        assert _parse_settings(settings_to_dict(Settings())) == Settings()

    def test_layout_to_dict(self):
        assert layout_to_dict(LayoutConfig()) == {"columns": 2, "rows": 1}

    def test_settings_to_dict_has_full_tools_map(self):
        assert settings_to_dict(Settings())["tools"] == dict(DEFAULT_TOOLS)


class TestGenerateConfigHasVersionAndFullSettings:
    def test_generate_config_has_version_and_full_settings(self, tmp_path):
        (tmp_path / "api" / ".git").mkdir(parents=True)
        config = generate_config(str(tmp_path))
        assert config["version"] == SCHEMA_VERSION
        # F-D6 divergence this factory kills: generators used to emit a
        # reduced 2-tool settings block missing happy/psmux/ssh/upload*.
        assert config["settings"]["tools"] == dict(DEFAULT_TOOLS)
        assert "happy" in config["settings"]
        assert "psmux" in config["settings"]
        assert "ssh" in config["settings"]
        assert "uploadServer" in config["settings"]
        assert "uploadPort" in config["settings"]


class TestProjectsToConfigUsesFactoryEnvelope:
    def test_projects_to_config_uses_factory_envelope(self, tmp_path):
        proj = tmp_path / "group" / "app"
        proj.mkdir(parents=True)
        projects = [{"path": str(proj), "tool": "claude", "session_count": 1, "last_active": 1}]
        config = projects_to_config(projects)
        assert config["version"] == SCHEMA_VERSION
        assert config["settings"]["tools"] == dict(DEFAULT_TOOLS)


class TestSingleSourceSettingsBlock:
    def test_single_source_settings_block(self, tmp_path):
        # generate_config, projects_to_config, and default_config must all
        # agree on settings/layout -- they're the same envelope now (R9).
        (tmp_path / "api" / ".git").mkdir(parents=True)
        generated = generate_config(str(tmp_path))

        proj = tmp_path / "group" / "app2"
        proj.mkdir(parents=True)
        discovered = projects_to_config(
            [{"path": str(proj), "tool": "claude", "session_count": 1, "last_active": 1}]
        )

        factory = default_config([])

        assert generated["settings"] == discovered["settings"] == factory["settings"]
        assert generated["layout"] == discovered["layout"] == factory["layout"]


class TestMigrateConfigFile:
    def test_migrate_stamps_version_and_persists_colors(self, tmp_config):
        path = tmp_config({
            "projects": [{"path": "api"}, {"path": "web", "color": "#123456"}],
        })

        changed = migrate_config_file(path)

        assert changed is True
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == SCHEMA_VERSION
        assert all("color" in p for p in data["projects"])
        assert data["projects"][1]["color"] == "#123456"  # pre-existing color untouched

        # A subsequent load_config must still write nothing (R10 stays pure
        # even for a file migrate just persisted to).
        before = Path(path).read_bytes()
        load_config(path)
        after = Path(path).read_bytes()
        assert before == after

    def test_migrate_is_idempotent(self, tmp_config):
        path = tmp_config({
            "version": SCHEMA_VERSION,
            "projects": [{"path": "api", "color": "#111111"}],
        })
        assert migrate_config_file(path) is False

    def test_migrate_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            migrate_config_file("/nonexistent/config.json")

    def test_migrate_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json{{{")
        with pytest.raises(ConfigError, match="valid JSON"):
            migrate_config_file(str(p))


class TestExampleConfigMatchesFactory:
    def test_example_config_matches_factory(self, tmp_path, capsys):
        with open(EXAMPLE_CONFIG_PATH, encoding="utf-8") as f:
            example = json.load(f)

        assert example["version"] == SCHEMA_VERSION
        assert example["settings"] == settings_to_dict(Settings())
        assert example["layout"] == layout_to_dict(LayoutConfig())
        # Teaches the remote/group/color/tool/enabled surfaces, not just defaults.
        assert any("host" in p for p in example["projects"])
        assert any("remotePath" in p for p in example["projects"])
        assert any("group" in p for p in example["projects"])
        assert any(p.get("enabled") is False for p in example["projects"])
        assert all("color" in p for p in example["projects"])
        assert any("tool" in p for p in example["projects"])

        # Round-trip through the public loader -- factory-dict equality alone
        # doesn't exercise the path real users hit (NF from MINOR's dropped pin).
        copy_path = tmp_path / "multideck.config.json"
        copy_path.write_text(json.dumps(example), encoding="utf-8")
        cfg = load_config(str(copy_path))

        assert cfg.version == SCHEMA_VERSION
        assert len(cfg.projects) == len(example["projects"])
        assert capsys.readouterr().err == ""
