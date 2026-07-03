from __future__ import annotations

from multideck.config import (
    DEFAULT_TOOLS,
    LayoutConfig,
    Settings,
    SCHEMA_VERSION,
    _parse_settings,
    default_config,
    layout_to_dict,
    settings_to_dict,
)
from multideck.discover import projects_to_config
from multideck.init_config import generate_config


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
