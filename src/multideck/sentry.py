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
        traces_sample_rate=0,
        send_default_pii=False,
        integrations=[
            LoggingIntegration(level=None, event_level=logging.ERROR),
            ThreadingIntegration(propagate_hub=True),
        ],
    )
    atexit.register(lambda: sentry_sdk.flush(timeout=2))
