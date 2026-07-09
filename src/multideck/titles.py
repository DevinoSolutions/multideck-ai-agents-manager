"""Window-title grammar — the single source for every multideck window title.

    title := "md:" [ "[" glyph "]" " " ] name
    glyph := "!" (needs-input) | "x" (error) | "+" (done)

The badge sits at the FRONT (right after the prefix) because taskbars truncate
title tails; a clean ``md:name`` title is the quiet working/idle state. Every
consumer that reads titles goes through ``parse_title`` and every producer
through ``make_title`` — nothing else may hand-build an ``md:`` string.
Constraint: project names must not themselves start with the ``[?] `` badge
shape; ``parse_title`` would strip it (accepted — enforced by convention).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multideck.config import WindowConfig

MD_TITLE_PREFIX = "md:"

# Attention states worth a badge; keys match multideck.agent_state values.
# working/idle deliberately have no badge — quiet title = nothing needs you.
STATE_BADGES: dict[str, str] = {
    "needs-input": "!",
    "error": "x",
    "done": "+",
}
_GLYPH_TO_STATE: dict[str, str] = {v: k for k, v in STATE_BADGES.items()}


def get_leaf_name(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized


def make_title(name: str, state: str | None = None) -> str:
    """Render a window title for ``name``, badged when ``state`` warrants one."""
    glyph = STATE_BADGES.get(state) if state else None
    if glyph is not None:
        return f"{MD_TITLE_PREFIX}[{glyph}] {name}"
    return f"{MD_TITLE_PREFIX}{name}"


def parse_title(title: str) -> tuple[str, str | None] | None:
    """Split a window title into ``(name, state)``.

    Returns None for titles that are not multideck's (no ``md:`` prefix).
    An unrecognized badge glyph is treated as part of the name rather than
    dropped, so a future glyph added by a newer writer degrades readably.
    """
    if not title.startswith(MD_TITLE_PREFIX):
        return None
    rest = title[len(MD_TITLE_PREFIX) :]
    if len(rest) >= 4 and rest[0] == "[" and rest[2] == "]" and rest[3] == " ":
        state = _GLYPH_TO_STATE.get(rest[1])
        if state is not None:
            return rest[4:], state
    return rest, None


def generate_titles(
    title: str | None,
    path: str,
    windows: list[WindowConfig] | None,
) -> list[str]:
    base = title or get_leaf_name(path)
    if not windows:
        return [base]
    titles: list[str] = []
    for i, w in enumerate(windows):
        titles.append(w.name if w.name else (base if i == 0 else f"{base}-{i + 1}"))
    return titles
