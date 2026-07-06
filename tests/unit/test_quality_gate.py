"""Regression guard for R1: the package must contain no syntax that is invalid
on the requires-python floor (3.10). Ruff auto-detects requires-python and flags
3.12-only f-string syntax on any interpreter (incl. 3.14), so this pins R1 even
on a 3.12+ dev machine where py_compile would pass."""

import shutil
import subprocess

import pytest


def test_no_python310_invalid_syntax():
    if shutil.which("ruff") is None:
        pytest.skip("ruff not installed")
    out = subprocess.run(
        ["ruff", "check", "src", "--output-format", "concise"],
        capture_output=True,
        text=True,
    ).stdout
    offenders = [ln for ln in out.splitlines() if "invalid-syntax" in ln]
    assert not offenders, "Py3.10-invalid syntax found:\n" + "\n".join(offenders)
