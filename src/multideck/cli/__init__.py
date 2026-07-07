"""Registration hub for the multideck CLI. `main` lives alone in app.py so
every command module can import it without a cycle (E6.md S2.1); importing
every command module below runs their `@main.command` decorators. The block
after that re-exports every symbol tests/external code still reach via
`multideck.cli.<name>`.
"""

from __future__ import annotations

from multideck.cli import (  # noqa: F401  # reason: side-effect import — runs each module's @main.command registration
    attach,
    attention_cmd,
    config_editor,
    config_io,
    daemons,
    docs,
    menu,
    session_picker,
    spawns,
    status,
    ui,
    watch,
)
from multideck.cli.app import main
from multideck.cli.attach import (
    _attach_flow,
    _default_attach_host,
    _split_target,
    _ssh_json,
    _tile_titles,
)
from multideck.cli.config_editor import _config_menu
from multideck.cli.menu import _run_discovery, _show_menu
from multideck.cli.session_picker import _run_sessions_picker
from multideck.cli.spawns import _maybe_start_hotkey
from multideck.cli.status import _menu_down, _menu_status, _menu_up
from multideck.cli.ui import _grouped, _print_session_overview

__all__ = [
    "_attach_flow",
    "_config_menu",
    "_default_attach_host",
    "_grouped",
    "_maybe_start_hotkey",
    "_menu_down",
    "_menu_status",
    "_menu_up",
    "_print_session_overview",
    "_run_discovery",
    "_run_sessions_picker",
    "_show_menu",
    "_split_target",
    "_ssh_json",
    "_tile_titles",
    "main",
]
