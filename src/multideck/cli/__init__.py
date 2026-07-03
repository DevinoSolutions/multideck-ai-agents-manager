from __future__ import annotations

from multideck.cli.app import main  # noqa: F401 -- re-exported: pyproject entry point `multideck.cli:main` + test suite
from multideck.cli.ui import _grouped, _print_session_overview  # noqa: F401 -- re-exported: test_attach.py direct access
from multideck.cli.config_editor import _config_menu  # noqa: F401 -- re-exported: test_cli_structure characterization; import triggers config group + 13-subcommand registration
from multideck.cli.docs import docs_cmd  # noqa: F401 -- import-time command registration
from multideck.cli.menu import _run_discovery, _show_menu  # noqa: F401 -- re-exported: app.py in-body dispatch import
from multideck.cli.attach import (  # noqa: F401 -- re-exported: app.py dispatch + test_attach/test_tiling direct access; import triggers up/attach/hotkey registration
    _attach_flow,
    _default_attach_host,
    _split_target,
    _ssh_json,
    _tile_titles,
)
from multideck.cli.session_picker import _run_sessions_picker  # noqa: F401 -- re-exported: app.py in-body dispatch import; import triggers sessions registration
from multideck.cli.daemons import mobile_cmd  # noqa: F401 -- import-time command registration
from multideck.cli.status import _menu_down, _menu_status, _menu_up  # noqa: F401 -- re-exported: app.py in-body dispatch import; import triggers status/down registration
from multideck.cli.spawns import _maybe_start_hotkey  # noqa: F401 -- re-exported: test_hotkey.py direct access
