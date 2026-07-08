"""Optional Sentry error reporting — env-gated, default OFF.

When MULTIDECK_SENTRY_DSN is unset: zero work, zero imports.
When set: init with errors-only (no traces), no PII, logging integration
at ERROR level (captures every logger.exception), excepthook, and
threading integrations. If the DSN is set but sentry-sdk isn't installed,
this prints an install tip to stderr rather than silently doing nothing.

Import this module in-body at CLI entry, after env validation.
"""

from __future__ import annotations

import logging

import click


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
        click.echo(
            "Sentry DSN is set but sentry-sdk is not installed -- error "
            'reporting is OFF. Install with: pip install -e ".[sentry]"',
            err=True,
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
