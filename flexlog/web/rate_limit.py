"""Flask-Limiter setup. The limiter is created lazily so importing
the module doesn't trigger Flask-Limiter's storage backend init —
useful for tests that don't enable rate limiting."""
from __future__ import annotations

import os

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

_limiter: Limiter | None = None


def install_rate_limiter(app: Flask) -> Limiter | None:
    """Attach a Limiter to the app. Returns the Limiter (or None if
    disabled via FLEXLOG_RATE_LIMIT != "1").

    Storage is in-memory (single Railway instance, no Redis needed).
    For multi-instance deploys, swap to a Redis backend."""
    global _limiter
    if os.environ.get("FLEXLOG_RATE_LIMIT", "0") != "1":
        return None
    if _limiter is not None:
        return _limiter
    _limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["100/hour"],
        storage_uri="memory://",
        strategy="fixed-window",
    )
    return _limiter


def apply_route_limits(app: Flask) -> None:
    """Apply per-route limits. Called from create_app AFTER blueprints
    are registered.

    Flask-Limiter's limit() decorator side-effects on the limit manager
    AND returns a wrapped function that performs the actual limit check.
    We must replace `app.view_functions[endpoint]` with that wrapped
    function for the check to fire on dispatch."""
    if _limiter is None:
        return
    if "landing.submit" in app.view_functions:
        original = app.view_functions["landing.submit"]
        app.view_functions["landing.submit"] = _limiter.limit("5 per hour")(original)


def get_limiter() -> Limiter | None:
    """Returns the live limiter, or None if rate limiting is disabled."""
    return _limiter


def _reset_for_testing():
    """Test-only helper. Each test that toggles FLEXLOG_RATE_LIMIT
    needs the module-level _limiter cleared so a fresh Limiter is
    constructed against the test's app instance."""
    global _limiter
    _limiter = None
