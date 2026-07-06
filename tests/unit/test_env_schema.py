"""Drift-pin: .env.example keys ⇔ MultideckEnv fields.

Same pattern as test_config_factory.py::TestExampleConfigMatchesFactory.
A new env var without an .env.example update = red gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from multideck.env import MultideckEnv

_ROOT = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = _ROOT / ".env.example"


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
