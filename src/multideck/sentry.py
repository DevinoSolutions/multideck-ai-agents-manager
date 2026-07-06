"""Optional Sentry error reporting — env-gated, default OFF.

When MULTIDECK_SENTRY_DSN is unset: zero work, zero imports.
When set: init with errors-only (no traces), no PII, logging integration
at ERROR level (captures every logger.exception), excepthook, and
threading integrations.

Import this module in-body at CLI entry, after env validation.
"""

from __future__ import annotations


def init_sentry(dsn: str) -> None:
    """Initialize Sentry SDK with the given DSN. Call once at CLI entry."""
    import atexit

    try:
        import sentry_sdk  # ty: ignore[unresolved-import]  # reason: optional dep, guarded by try/except
        from sentry_sdk.integrations.logging import (  # ty: ignore[unresolved-import]  # reason: optional dep
            LoggingIntegration,
        )
        from sentry_sdk.integrations.threading import (  # ty: ignore[unresolved-import]  # reason: optional dep
            ThreadingIntegration,
        )
    except ImportError:
        return

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0,
        send_default_pii=False,
        integrations=[
            LoggingIntegration(level=None, event_level="ERROR"),
            ThreadingIntegration(propagate_hub=True),
        ],
    )
    atexit.register(lambda: sentry_sdk.flush(timeout=2))
