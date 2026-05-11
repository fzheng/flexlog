"""Regression: the Flask appcontext teardown that closes the per-request
DB session must fire after a runtime engine attach.

Before this fix, `attach_to_app` registered the teardown but
`attach_engine_at_runtime` did not. Post-v0.2.0 the app no longer calls
`attach_to_app` at boot — the engine is only attached at login via
`attach_engine_at_runtime`. So the teardown was never registered, and
every per-request session leaked.

The fix moves teardown registration into `register_db_teardown(app)`
which is called once at app-factory time, before any engine is attached."""
from __future__ import annotations


def test_db_session_closed_after_request(authed_client):
    """After a DB-touching request, the request-scoped Session must be
    removed from Flask's `g` object. Re-entering the app context should
    not still hold the previous session."""
    # Hit the dashboard (mounted at /). It opens a DB session via get_db().
    resp = authed_client.get("/")
    assert resp.status_code == 200

    from flask import g

    # Inside a fresh app context, `g` should not carry any session — the
    # teardown handler must have popped it at the end of the prior request.
    with authed_client.application.app_context():
        assert "_flexlog_db_session" not in g, (
            "previous request's session leaked into a fresh app context — "
            "teardown handler did not fire after attach_engine_at_runtime"
        )


def test_teardown_registered_at_app_factory_time(app):
    """The appcontext teardown must be registered on the Flask app even
    BEFORE any engine is attached — so attach_engine_at_runtime callers
    (login, setup) don't have to remember to register one themselves."""
    teardowns = getattr(app, "teardown_appcontext_funcs", [])
    qualnames = [getattr(fn, "__qualname__", repr(fn)) for fn in teardowns]
    # `register_db_teardown` defines a nested function `_close` — match on it
    assert any("_close" in q or "close_db" in q for q in qualnames), (
        f"no DB-close teardown registered; have: {qualnames}"
    )


def test_session_close_called_on_appcontext_pop(app):
    """End-to-end: open a Session via get_db() inside an app_context, leave
    the context, and confirm the request-scoped session was closed by the
    teardown handler (i.e. the Session object's .close() was invoked)."""
    from unittest.mock import patch
    from flexlog.db import get_db

    with app.app_context():
        sess = get_db()
        with patch.object(sess, "close", wraps=sess.close) as spy:
            pass  # context manager exit triggers teardown_appcontext
        # The patch context closes BEFORE app_context exits, so the spy
        # won't see the call. Re-do it the other way:

    closed = {"called": False}
    with app.app_context():
        sess = get_db()
        original_close = sess.close

        def spy_close():
            closed["called"] = True
            return original_close()

        sess.close = spy_close
        # Leaving the with-block pops the appcontext, fires the teardown,
        # which calls close_db(), which calls sess.close().

    assert closed["called"], (
        "Session.close() was not invoked when the appcontext was popped — "
        "the teardown handler did not run"
    )
