"""Shared click.style shortcut, hoisted out of cli.py and launch.py where it
was independently defined twice (LS-A-003, duplication). `S` is kept as a
transitional alias for the existing call sites across the codebase; `style`
is the preferred name for new code. The repo-wide S -> style rename at call
sites is a separate, larger cleanup (E10), not done here.
"""
from __future__ import annotations

import click

style = click.style
S = style
