#!/usr/bin/env python
"""Custom repo-rule lint layer — the rules ruff has no plugin API for.

Stdlib-only (`ast`, `tokenize`, `io`, `pathlib`). Emits one
``path:line:col: MDxxx message`` per finding and exits 1 if any fire, 0 if
clean. Wired into ``scripts/check.py`` (both modes) and covered snippet-by-
snippet in ``tests/unit/test_lint_rules.py``.

Rules
-----
MD001  No ``sys.exit(...)`` / ``raise SystemExit`` outside ``src/multideck/cli/``.
       Subsystems return ints or raise; the exit decision lives in the shells.
MD002  No ``sys.platform`` outside ``src/multideck/platform/`` unless the file is
       on the reasoned MD002_ALLOW list (genuinely OS-behavioral dispatch, not a
       capability gate — capability questions use ``Platform.supports_*()``).
MD003  No ``"md:"`` string / f-string literal outside ``titles.py`` and
       ``cli/attach.py``. The window-title prefix is built only from
       ``titles.MD_TITLE_PREFIX``.
MD004  Every suppression comment (``# noqa`` / ``# type: ignore`` / ``# ty: ignore``)
       must carry a ``reason:`` text — the no-naked-suppressions policy, mechanized.

Scopes: MD001/002/003 apply to ``src/multideck/`` only; MD004 applies to
``src`` + ``scripts`` + ``tests``.
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent

SRC_PREFIX = "src/multideck/"
CLI_PREFIX = "src/multideck/cli/"
PLATFORM_PREFIX = "src/multideck/platform/"

# MD002: files outside platform/** that legitimately branch on sys.platform for
# OS-behavioral dispatch — path/env semantics, process primitives, editor /
# terminal / console commands. None are capability-gates-in-disguise (those use
# Platform.supports_*()). Each entry is (relpath -> why it is OS-behavioral).
MD002_ALLOW = {
    "src/multideck/paths.py": "config-dir location is per-OS (APPDATA / XDG / Library)",
    "src/multideck/discover.py": "session-store paths, path separators, FS case-folding",
    "src/multideck/agent_state.py": "state-store path differs per OS",
    "src/multideck/terminals.py": "terminal-emulator selection is inherently per-OS",
    "src/multideck/launch.py": "Windows job-object breakaway in spawn_detached",
    "src/multideck/upload_server.py": "taskkill vs os.kill process termination",
    "src/multideck/cli/attention_cmd.py": "taskkill vs os.kill process termination",
    "src/multideck/hotkey.py": "module is Windows-only by construction (raises off-win32)",
    "src/multideck/sessions/codex.py": "FS case-insensitivity for session-path matching",
    "src/multideck/cli/ui.py": "OS-specific editor command + Windows console UTF-8 fix",
    "src/multideck/cli/spawns.py": "OpenProcess vs os.kill pid-liveness primitive",
    "src/multideck/cli/session_picker.py": "terminal reset (cls vs stty/tput) is per-OS",
    "src/multideck/cli/attach.py": "reports the sys.platform value in JSON status (data, not a gate)",
    "src/multideck/env.py": "host-env readers (config_base, vscode_storage_base) select per-OS default directories",
}

# MD003: the only two src files allowed to hold a literal "md:".
MD003_ALLOW = {"src/multideck/titles.py", "src/multideck/cli/attach.py"}

# MD004: a comment is a suppression directive when, after its leading '#' and
# spaces, it *begins* with one of these — so prose that merely mentions the word
# (or a marker inside a string literal, which is not a COMMENT token) is exempt.
_SUPPRESSION_STARTS = ("noqa", "type: ignore", "type:ignore", "ty: ignore", "ty:ignore")


class Finding(NamedTuple):
    path: str  # repo-relative, posix
    line: int
    col: int  # 1-based
    code: str
    message: str


def _is_sys_exit(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exit"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sys"
    )


def _is_raise_systemexit(node: ast.AST) -> bool:
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    exc: ast.AST = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "SystemExit"


def _is_sys_platform(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "platform"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _starts_md(node: ast.AST) -> bool:
    """True if node is a str literal, or an f-string, whose text begins 'md:'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.startswith("md:")
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value.startswith("md:")
    return False


def _ast_rules(rel: str, source: str) -> list[Finding]:
    """MD001/002/003 — src/multideck/ only."""
    out: list[Finding] = []
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError as e:
        return [
            Finding(
                rel,
                e.lineno or 1,
                (e.offset or 0) + 1,
                "MD000",
                f"syntax error: {e.msg}",
            )
        ]

    in_cli = rel.startswith(CLI_PREFIX)
    in_platform = rel.startswith(PLATFORM_PREFIX)
    md002_allowed = in_platform or rel in MD002_ALLOW
    md003_allowed = rel in MD003_ALLOW

    # Constants that are pieces of an f-string are counted via their JoinedStr
    # parent (below), never again as standalone literals — so f"md:{x}" flags once.
    fstring_pieces = {
        id(v)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for v in node.values
        if isinstance(v, ast.Constant)
    }

    for node in ast.walk(tree):
        col = getattr(node, "col_offset", 0) + 1
        line = getattr(node, "lineno", 1)
        if not in_cli and (_is_sys_exit(node) or _is_raise_systemexit(node)):
            out.append(
                Finding(
                    rel,
                    line,
                    col,
                    "MD001",
                    "sys.exit/SystemExit outside cli/ — subsystems return ints or raise; the exit decision lives in the shells",
                )
            )
        if not md002_allowed and _is_sys_platform(node):
            out.append(
                Finding(
                    rel,
                    line,
                    col,
                    "MD002",
                    "sys.platform outside platform/ — gate on a Platform.supports_*() probe, or add a reasoned MD002_ALLOW entry if genuinely OS-behavioral",
                )
            )
        if not md003_allowed and _starts_md(node) and id(node) not in fstring_pieces:
            out.append(
                Finding(
                    rel,
                    line,
                    col,
                    "MD003",
                    'string literal starting "md:" — the window-title prefix is built only from titles.MD_TITLE_PREFIX',
                )
            )
    return out


def _suppression_rule(rel: str, source: str) -> list[Finding]:
    """MD004 — every suppression comment must carry a reason: text."""
    out: list[Finding] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            body = tok.string.lstrip("#").strip().lower()
            if (
                body.startswith(_SUPPRESSION_STARTS)
                and "reason:" not in tok.string.lower()
            ):
                out.append(
                    Finding(
                        rel,
                        tok.start[0],
                        tok.start[1] + 1,
                        "MD004",
                        "suppression comment without a `reason:` — every # noqa / # type: ignore / # ty: ignore must state why",
                    )
                )
    except (tokenize.TokenError, IndentationError):
        # A malformed token stream is ruff/compileall's job to report, not ours.
        pass
    return out


def check_source(rel: str, source: str) -> list[Finding]:
    """All findings for one file, keyed by its repo-relative posix path."""
    out: list[Finding] = []
    if rel.startswith(SRC_PREFIX):
        out += _ast_rules(rel, source)
    if rel.startswith(("src/", "scripts/", "tests/")):
        out += _suppression_rule(rel, source)
    return out


def check_tree(root: Path) -> list[Finding]:
    """Scan src/, scripts/, tests/ under root and return sorted findings."""
    findings: list[Finding] = []
    for sub in ("src", "scripts", "tests"):
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            try:
                source = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                findings.append(Finding(rel, 1, 1, "MD000", f"could not read: {e}"))
                continue
            findings += check_source(rel, source)
    return sorted(findings)


def main() -> int:
    findings = check_tree(REPO_ROOT)
    for f in findings:
        print(f"{f.path}:{f.line}:{f.col}: {f.code} {f.message}")
    if findings:
        print(f"\n{len(findings)} custom-rule finding(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
