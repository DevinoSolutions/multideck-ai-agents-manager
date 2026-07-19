"""Optional Sentry error reporting — env-gated, default OFF.

When MULTIDECK_SENTRY_DSN is unset: zero work, zero imports.
When set: init with errors-only (no traces), no PII, logging integration
at ERROR level (captures every logger.exception), excepthook, and
threading integrations. If the DSN is set but sentry-sdk isn't installed,
init degrades to a rotating-log warning — never a console nag: init runs
at CLI entry for EVERY command, so a stderr tip would tax unrelated
commands (`attach`, `status`, …) for an optional feature the command never
asked for. The actionable install hint surfaces in `multideck doctor`.

Import this module in-body at CLI entry, after env validation.
"""

from __future__ import annotations

import logging

from multideck.log import get_logger

# The hint a USER can act on: the installed-package extra. (A dev checkout
# would use `pip install -e ".[sentry]"`, but users hitting this run the
# published wheel — the -e form used to be shown and was wrong for them.)
SENTRY_INSTALL_HINT = 'pip install "multideck[sentry]"'


def sdk_installed() -> bool:
    """True when the optional ``sentry-sdk`` package is importable — probed
    via find_spec so the check never actually imports the SDK. Used by
    `multideck doctor` to surface the DSN-set-but-SDK-missing state."""
    from importlib.util import find_spec

    try:
        return find_spec("sentry_sdk") is not None
    except (ImportError, ValueError):
        # ValueError: sys.modules["sentry_sdk"] is None (how tests simulate
        # the package being absent).
        return False


def _release() -> str | None:
    """The installed distribution version, tagged on every event as the Sentry
    release so a report is pinned to a build -- not to whatever git HEAD the
    process happened to run beside. ``None`` (Sentry omits the tag) when the
    package isn't installed as a distribution, e.g. a bare source checkout."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("multideck")
    except PackageNotFoundError:
        return None


def init_sentry(dsn: str) -> None:
    """Initialize Sentry SDK with the given DSN. Call once at CLI entry."""
    import atexit

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.threading import ThreadingIntegration
    except ImportError:
        # Quiet degradation by design (was a stderr echo): the console must not
        # nag on every command; doctor carries the actionable hint.
        get_logger("sentry").warning(
            "MULTIDECK_SENTRY_DSN is set but sentry-sdk is not installed -- "
            "error reporting is OFF. Install: %s",
            SENTRY_INSTALL_HINT,
        )
        return

    sentry_sdk.init(
        dsn=dsn,
        # multideck is a single-operator dev tool today (CI never inits Sentry),
        # so the environment is fixed to "dev" -- without minting a new MULTIDECK_
        # env var, which would break the closed-schema contract for one knob. A
        # future deployment story (prod/staging) would parameterize this.
        environment="dev",
        release=_release(),
        # server_name (hostname) + sys.argv ride along via Sentry's default
        # integrations. Kept on purpose: this is a self-hosted, single-operator
        # setup where "which machine, what command" is exactly the debugging
        # context wanted, and send_default_pii=False is the actual PII gate.
        traces_sample_rate=0,
        send_default_pii=False,
        integrations=[
            LoggingIntegration(level=None, event_level=logging.ERROR),
            ThreadingIntegration(propagate_hub=True),
        ],
    )
    atexit.register(lambda: sentry_sdk.flush(timeout=2))
