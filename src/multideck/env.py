"""Validated environment schema — the single module that touches process env.

App-config variables (MULTIDECK_*) are validated via pydantic-settings:
unknown MULTIDECK_ vars = hard error (closed schema). Host-infrastructure
variables (APPDATA, XDG_CONFIG_HOME, LOCALAPPDATA, EDITOR) are defaulted
reads — not validated app config; the two concerns are visibly separate.

Env errors are pre-Sentry by construction: the DSN comes from env, so
a bad env can't be reported to Sentry.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic_settings import BaseSettings

if TYPE_CHECKING:
    from pydantic import HttpUrl


class MultideckEnv(BaseSettings):
    """Validated MULTIDECK_* environment variables.

    ``extra="forbid"`` means any unknown ``MULTIDECK_*`` var is a hard error
    (closed schema — same doctrine as the config file).
    """

    model_config = {"env_prefix": "MULTIDECK_", "env_file": ".env", "extra": "forbid"}

    sentry_dsn: HttpUrl | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None


_cached_env: MultideckEnv | None = None


def get_env() -> MultideckEnv:
    """Return the validated env singleton (instantiated on first call)."""
    global _cached_env  # noqa: PLW0603  # reason: module-level cache singleton pattern
    if _cached_env is None:
        _cached_env = MultideckEnv()
    return _cached_env


# --- Host-infrastructure env reads -----------------------------------------
# These are NOT app-config: they are OS-convention variables with sensible
# defaults. Grouped here so TID251 can ban os.environ everywhere else.


def appdata_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def localappdata_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", ""))


def editor_command() -> str:
    return os.environ.get("EDITOR", "xdg-open")


def config_base() -> Path:
    """The platform-appropriate config base directory."""
    if sys.platform == "win32":
        return appdata_dir()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return xdg_config_home()


def vscode_storage_base() -> Path:
    """The platform-appropriate VS Code workspace storage parent."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", ""))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
