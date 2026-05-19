"""End-to-end auth tests: fake landing, login, idle expiry, restart, logout."""
from __future__ import annotations

import time

import pytest


def test_anonymous_get_root_renders_fake_landing(client):
    """GET / by an anonymous user shows the fake Google homepage, NOT the dashboard."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Page replicates google.com — title, logo wordmark, and search button all present
    assert "<title>Google</title>" in body
    assert 'class="g-logo"' in body
    assert "Google Search" in body
    assert "I&#39;m Feeling Lucky" in body or "I'm Feeling Lucky" in body
    # Must not leak any flexlog-specific label or route path. (The
    # legitimate Google footer link "Settings" is allowed — it points at
    # google.com/preferences, which is part of the disguise; we check
    # routes instead to detect leaks.)
    for noun in ("New Guest", "Add Interview", "Media Library", "Edit Person",
                 "flexlog", "/dashboard", "/people/", "/sessions/", "/library"):
        assert noun not in body, f"fake page leaked {noun!r}"


def test_wrong_password_post_redirects_to_google(client):
    resp = client.post("/", data={"q": "hello world"})
    assert resp.status_code == 303
    loc = resp.headers["Location"]
    assert loc.startswith("https://www.google.com/search?")
    assert "q=hello+world" in loc or "q=hello%20world" in loc


def test_empty_q_post_re_renders_landing(client):
    resp = client.post("/", data={"q": ""})
    assert resp.status_code == 200
    assert 'class="g-logo"' in resp.get_data(as_text=True)


def test_correct_password_logs_in(client, admin_password):
    resp = client.post("/", data={"q": admin_password})
    assert resp.status_code == 303
    # 303 returns to / — which (now authed) renders the dashboard inline.
    loc = resp.headers["Location"]
    assert loc.endswith("/") or loc.endswith("/dashboard")
    # And subsequent dashboard request returns 200 (auth cookie applied).
    resp2 = client.get("/dashboard")
    assert resp2.status_code == 200


def test_protected_route_redirects_anonymous(client):
    resp = client.get("/people/new")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/")


def test_protected_route_works_for_authed(authed_client):
    resp = authed_client.get("/people/new")
    assert resp.status_code == 200


def test_idle_expiry_unsets_auth(authed_client):
    """31 minutes of idle time invalidates the session."""
    with authed_client.session_transaction() as sess:
        sess["last_seen"] = time.time() - (31 * 60)
    resp = authed_client.get("/dashboard")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/")


def test_server_restart_invalidates_via_epoch_mismatch(authed_client):
    """Mutating AUTH_EPOCH simulates a server restart."""
    authed_client.application.config["AUTH_EPOCH"] = "different-epoch-token"
    resp = authed_client.get("/dashboard")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/")


def test_logout_clears_session(authed_client):
    resp = authed_client.post("/logout")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/")
    # After logout, dashboard redirects to /
    resp2 = authed_client.get("/dashboard")
    assert resp2.status_code == 303
    assert resp2.headers["Location"].endswith("/")


def test_logout_drops_master_key_and_engine_from_config(authed_client):
    """Defense in depth (I1): logout must remove MASTER_KEY + the DB
    engine reference from app.config. A buggy route added to the unauth
    allowlist by mistake then cannot reach user data via get_db()."""
    app = authed_client.application
    # Pre-state: authed_client fixture has logged in, so both should be present.
    assert app.config.get("MASTER_KEY") is not None, "fixture should be logged in"
    assert app.config.get("FLEXLOG_DB_ENGINE") is not None

    authed_client.post("/logout")

    assert app.config.get("MASTER_KEY") is None, \
        "MASTER_KEY must be removed from app.config on logout"
    assert app.config.get("FLEXLOG_DB_ENGINE") is None, \
        "DB engine must be detached on logout"


def test_missing_kdf_params_redirects_to_setup(monkeypatch, tmp_path):
    """When no kdf_params.json + no DB, GET / 303s to the set-password page."""
    from flexlog.config_loader import DEFAULT_CONFIG_JSON

    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FLEXLOG_ADMIN_PASSWORD_SHA512", raising=False)
    (tmp_path / "config.json").write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")

    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 303
    assert "/setup/set-password" in resp.headers["Location"]
