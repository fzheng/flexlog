"""Unit tests for flexlog.auth — session helpers + password verification."""
from __future__ import annotations

import hashlib

import pytest

from flexlog.auth import (
    IDLE_TIMEOUT_SEC,
    is_authed,
    mark_authed,
    mark_unauthed,
    validate_admin_hash,
    verify_password,
)


def _h(s: str) -> str:
    return hashlib.sha512(s.encode()).hexdigest()


def test_idle_timeout_is_30_minutes():
    assert IDLE_TIMEOUT_SEC == 30 * 60


def test_verify_password_correct():
    assert verify_password("hunter2", _h("hunter2")) is True


def test_verify_password_wrong():
    assert verify_password("nope", _h("hunter2")) is False


def test_verify_password_uses_constant_time_compare():
    """Smoke: verify_password should call hmac.compare_digest, not ==."""
    import flexlog.auth as auth_mod
    src = open(auth_mod.__file__).read()
    assert "hmac.compare_digest" in src
    # And should NOT use a plain == on the hashes
    assert "expected_hash_hex ==" not in src


def test_validate_admin_hash_accepts_valid_hex():
    h = _h("x")
    assert validate_admin_hash(h) == h


def test_validate_admin_hash_rejects_wrong_length():
    with pytest.raises(ValueError, match="128"):
        validate_admin_hash("abc")


def test_validate_admin_hash_rejects_uppercase():
    h = _h("x").upper()
    with pytest.raises(ValueError, match="lowercase"):
        validate_admin_hash(h)


def test_validate_admin_hash_rejects_non_hex():
    bad = "g" * 128
    with pytest.raises(ValueError, match="hex"):
        validate_admin_hash(bad)


def test_mark_authed_sets_session_keys():
    session: dict = {}
    config = {"AUTH_EPOCH": "abc123"}
    mark_authed(session, config)
    assert session["authed"] is True
    assert session["epoch"] == "abc123"
    assert isinstance(session["last_seen"], float)


def test_mark_unauthed_pops_keys():
    session = {"authed": True, "epoch": "x", "last_seen": 123.0, "other": "keep"}
    mark_unauthed(session)
    assert "authed" not in session
    assert "epoch" not in session
    assert "last_seen" not in session
    assert session["other"] == "keep"


def test_is_authed_false_when_no_keys():
    assert is_authed({}, {"AUTH_EPOCH": "x"}) is False


def test_is_authed_false_when_epoch_mismatch():
    import time
    session = {"authed": True, "epoch": "old", "last_seen": time.time()}
    assert is_authed(session, {"AUTH_EPOCH": "new"}) is False


def test_is_authed_false_when_idle_too_long():
    import time
    session = {"authed": True, "epoch": "x", "last_seen": time.time() - 31 * 60}
    assert is_authed(session, {"AUTH_EPOCH": "x"}) is False


def test_is_authed_true_and_refreshes_last_seen():
    import time
    old_seen = time.time() - 60
    session = {"authed": True, "epoch": "x", "last_seen": old_seen}
    assert is_authed(session, {"AUTH_EPOCH": "x"}) is True
    assert session["last_seen"] > old_seen


# ----------------------------------------------------------- Edge cases

def test_validate_admin_hash_rejects_non_string():
    """A non-string input (e.g. None passed by a misconfigured loader)
    must produce a clear error, not a TypeError or AttributeError."""
    with pytest.raises(ValueError, match="must be a string"):
        validate_admin_hash(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be a string"):
        validate_admin_hash(12345)  # type: ignore[arg-type]


def test_is_authed_false_when_last_seen_is_garbage():
    """If the cookie was tampered with so last_seen isn't a number,
    treat as unauth — never crash on time arithmetic."""
    session = {"authed": True, "epoch": "x", "last_seen": "not-a-float"}
    assert is_authed(session, {"AUTH_EPOCH": "x"}) is False
    # Same for missing key entirely
    session2 = {"authed": True, "epoch": "x"}
    assert is_authed(session2, {"AUTH_EPOCH": "x"}) is False


def test_is_authed_false_when_authed_is_falsy():
    """authed=False / 0 / empty string all mean "not logged in" — only
    the truthy case opens the door."""
    for val in (False, 0, "", None):
        session = {"authed": val}
        assert is_authed(session, {"AUTH_EPOCH": "x"}) is False


def test_mark_unauthed_idempotent():
    """Calling mark_unauthed on a session that was never authed must not
    raise — the route layer may invoke it defensively after errors."""
    session: dict = {}
    mark_unauthed(session)  # no-op
    assert session == {}
