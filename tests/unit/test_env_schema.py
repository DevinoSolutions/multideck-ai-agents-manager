"""Drift-pin: .env.example keys ⇔ MultideckEnv fields.

Same pattern as test_config_factory.py::TestExampleConfigMatchesFactory.
A new env var without an .env.example update = red gate.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from multideck import cli
from multideck import env as env_module
from multideck.env import MultideckEnv

_ROOT = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = _ROOT / ".env.example"


def _clear_multideck_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every ambient MULTIDECK_* var (including the repo's real .env
    values, once loaded) so tests start from a known-empty schema."""
    for key in list(os.environ):
        if key.upper().startswith("MULTIDECK_"):
            monkeypatch.delenv(key, raising=False)


def _example_keys() -> set[str]:
    """Parse commented-out MULTIDECK_* keys from .env.example."""
    keys: set[str] = set()
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"#?\s*(MULTIDECK_\w+)\s*=", line)
        if m:
            keys.add(m.group(1))
    return keys


def _schema_keys() -> set[str]:
    """MULTIDECK_* env-var names implied by MultideckEnv fields."""
    prefix = "MULTIDECK_"
    return {f"{prefix}{name.upper()}" for name in MultideckEnv.model_fields}


class TestEnvExampleMatchesSchema:
    def test_example_keys_match_schema(self) -> None:
        example = _example_keys()
        schema = _schema_keys()
        assert example == schema, (
            f"Drift detected between .env.example and MultideckEnv.\n"
            f"  In example but not schema: {example - schema}\n"
            f"  In schema but not example: {schema - example}"
        )

    def test_example_file_exists(self) -> None:
        assert _ENV_EXAMPLE.is_file(), ".env.example must be committed"

    @pytest.mark.parametrize("key", sorted(_schema_keys()))
    def test_each_schema_key_in_example(self, key: str) -> None:
        assert key in _example_keys(), f"{key} missing from .env.example"


class TestClosedSchemaRejectsUnknownVars:
    """R2-01: extra="forbid" alone never sees env-sourced keys — the
    _no_unknown_multideck_vars validator is what actually closes the schema."""

    def test_unknown_var_is_a_hard_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_multideck_env(monkeypatch)
        monkeypatch.setenv("MULTIDECK_TOTALLY_UNKNOWN", "1")
        with pytest.raises(ValidationError):
            MultideckEnv(_env_file=None)

    def test_known_vars_still_validate_fine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_multideck_env(monkeypatch)
        monkeypatch.setenv("MULTIDECK_LOG_LEVEL", "DEBUG")
        env = MultideckEnv(_env_file=None)
        assert env.log_level == "DEBUG"


class TestCliFailsFastOnBadEnv:
    """R2-02: a malformed/unknown MULTIDECK_* var must exit 1 with a plain
    stderr message naming the variable — never a raw pydantic traceback."""

    def test_bad_log_level_exits_nonzero_naming_the_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_multideck_env(monkeypatch)
        monkeypatch.setenv("MULTIDECK_LOG_LEVEL", "BOGUS")
        monkeypatch.setattr(env_module, "_cached_env", None)

        result = CliRunner().invoke(cli.main, [])

        assert result.exit_code == 1
        assert "MULTIDECK_LOG_LEVEL" in result.output
        assert "Traceback" not in result.output

    def test_unknown_var_exits_nonzero_without_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_multideck_env(monkeypatch)
        monkeypatch.setenv("MULTIDECK_TOTALLY_UNKNOWN", "1")
        monkeypatch.setattr(env_module, "_cached_env", None)

        result = CliRunner().invoke(cli.main, [])

        assert result.exit_code == 1
        assert "MULTIDECK_TOTALLY_UNKNOWN" in result.output
        assert "Traceback" not in result.output

    def test_unknown_var_in_dotenv_names_it_exactly_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R5-01: a .env extra_forbidden error carries the full MULTIDECK_*
        key in loc (unlike field errors, which carry the bare field name) —
        the formatter must not double the prefix."""
        _clear_multideck_env(monkeypatch)
        monkeypatch.setattr(env_module, "_cached_env", None)

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path(".env").write_text("MULTIDECK_FOO=1\n", encoding="utf-8")
            result = runner.invoke(cli.main, [])

        assert result.exit_code == 1
        assert "MULTIDECK_FOO: " in result.output
        assert "MULTIDECK_MULTIDECK" not in result.output
        assert "Traceback" not in result.output
