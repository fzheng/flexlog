"""Session-based admin auth + password verification.

Sessions live in Flask's signed cookie. We store three keys:
  * authed     : True once the password has been verified
  * epoch      : equals app.config['AUTH_EPOCH'] at the moment of login;
                 a process restart generates a new epoch which makes all
                 prior cookies invalid
  * last_seen  : float, time.time() of the most recent authed request;
                 updated on every authed request to implement the
                 30-minute sliding idle window

The module deliberately holds no Flask imports beyond the type used by
type hints — keeps it unit-testable with plain dicts.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Any, MutableMapping

# 30-minute sliding idle window per spec.
IDLE_TIMEOUT_SEC = 30 * 60

# Endpoints that must remain reachable while unauthed. The before_request
# auth gate consults this set; everything not in it gets a 303 to /.
ALLOWED_UNAUTH_ENDPOINTS = frozenset({
    "landing.index",      # GET /
    "landing.submit",     # POST /
    "landing.robots_txt", # GET /robots.txt
    "auth.logout",        # POST /logout (no-op when unauthed, harmless)
    "static",             # CSS / JS / vendor assets
})

_HEX_HASH_RE = re.compile(r"^[0-9a-f]{128}$")


def validate_admin_hash(value: str) -> str:
    """Validate a SHA-512 hex string. Returns the hash unchanged if valid;
    raises ValueError with a clear message otherwise."""
    if not isinstance(value, str):
        raise ValueError("admin password hash must be a string")
    if len(value) != 128:
        raise ValueError(
            f"admin password hash must be 128 hex chars (got {len(value)}); "
            "is this a SHA-512 hex digest?"
        )
    if value != value.lower():
        raise ValueError("admin password hash must be lowercase hex")
    if not _HEX_HASH_RE.match(value):
        raise ValueError("admin password hash must be hex (0-9, a-f only)")
    return value


def verify_password(typed: str, expected_hash_hex: str) -> bool:
    """Constant-time comparison of SHA-512(typed) against the stored hash."""
    typed_hash = hashlib.sha512(typed.encode("utf-8")).hexdigest()
    return hmac.compare_digest(typed_hash, expected_hash_hex)


def mark_authed(session: MutableMapping[str, Any], app_config: MutableMapping[str, Any]) -> None:
    """Mark the session as authenticated. Flask saves the session cookie at
    end of request — no explicit commit required."""
    session["authed"] = True
    session["epoch"] = app_config["AUTH_EPOCH"]
    session["last_seen"] = time.time()


def mark_unauthed(session: MutableMapping[str, Any]) -> None:
    """Drop auth-related keys from the session. Other keys (e.g. flash
    messages) survive."""
    session.pop("authed", None)
    session.pop("epoch", None)
    session.pop("last_seen", None)


def is_authed(
    session: MutableMapping[str, Any],
    app_config: MutableMapping[str, Any],
) -> bool:
    """Return True iff the session has a valid auth marker, the recorded
    epoch matches app_config['AUTH_EPOCH'], and the last activity is within
    the idle window. Side effect: refreshes session['last_seen'] when all
    checks pass (sliding window).

    On any failure the session is left untouched so the caller can decide
    whether to redirect or clear (the before_request hook clears stale
    sessions explicitly to avoid leaking the prior epoch in the cookie)."""
    if not session.get("authed"):
        return False
    if session.get("epoch") != app_config.get("AUTH_EPOCH"):
        return False
    last_seen = session.get("last_seen")
    if not isinstance(last_seen, (int, float)):
        return False
    if time.time() - last_seen > IDLE_TIMEOUT_SEC:
        return False
    session["last_seen"] = time.time()
    return True
