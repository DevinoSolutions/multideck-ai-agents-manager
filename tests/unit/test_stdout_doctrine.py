"""Test-doctrine guard: no ``json.loads(<...>.output)`` anywhere in tests/ (P5-03).

Click 8.4's ``CliRunner`` merges stderr into ``result.output``; a stderr
diagnostic (e.g. the config-version warning) then corrupts a JSON body parsed
from it. JSON-body assertions must read ``result.stdout``. This test mechanizes
the NF-S3-002 doctrine so a new ``json.loads(result.output)`` fails loudly here,
by name, instead of surfacing as a confusing ``JSONDecodeError`` elsewhere.
"""

from __future__ import annotations

import ast
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent.parent  # the tests/ root


def _has_output_attr(node: ast.AST) -> bool:
    """True if the expression subtree reads an ``<x>.output`` attribute."""
    return any(
        isinstance(n, ast.Attribute) and n.attr == "output" for n in ast.walk(node)
    )


def _is_json_loads(func: ast.expr) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "loads"
        and isinstance(func.value, ast.Name)
        and func.value.id == "json"
    )


def _offending_lines(source: str) -> list[int]:
    """Line numbers of ``json.loads(...)`` calls whose argument reads ``.output``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []  # a broken test file is compileall/ruff's problem, not ours
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _is_json_loads(node.func)
        and any(_has_output_attr(arg) for arg in node.args)
    ]


def test_no_json_loads_on_result_output():
    offenders: list[str] = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        for lineno in _offending_lines(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(_TESTS_DIR).as_posix()}:{lineno}")
    assert not offenders, (
        "json.loads(...) reading a `.output` attribute — Click merges stderr into "
        ".output; parse JSON bodies from result.stdout (NF-S3-002). Offenders: "
        f"{offenders}"
    )
