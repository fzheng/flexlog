"""Shared pytest fixtures for flexlog tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flexlog.config_loader import DEFAULT_CONFIG_JSON


@pytest.fixture
def tmp_data_dir_no_config(tmp_path, monkeypatch):
    """An existing, writable data dir with NO config.json yet."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """An existing, writable data dir with the canonical default config.json
    AND a .env containing the test admin password hash."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
    # Also seed the admin password hash so create_app() doesn't refuse to start.
    import hashlib
    pw_hash = hashlib.sha512(b"hunter2").hexdigest()
    (tmp_path / ".env").write_text(
        f"FLEXLOG_ADMIN_PASSWORD_SHA512={pw_hash}\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def admin_password() -> str:
    return "hunter2"


@pytest.fixture
def admin_password_hash(admin_password) -> str:
    import hashlib
    return hashlib.sha512(admin_password.encode()).hexdigest()


@pytest.fixture
def app(tmp_data_dir):
    """App with CSRF DISABLED — used by the vast majority of tests.

    A separate `csrf_app` fixture is provided for the one CSRF integration
    test that actually needs the protection wired in.
    """
    from flexlog.app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_app(tmp_data_dir):
    """App with CSRF enabled — for tests that exercise CSRF rejection."""
    from flexlog.app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    # WTF_CSRF_ENABLED stays True (the default in production)
    return flask_app


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


@pytest.fixture
def authed_client(client):
    """Test client with the auth session pre-populated. Bypasses the actual
    login POST for speed; the auth flow itself is covered by tests in
    test_auth.py."""
    import time
    with client.session_transaction() as sess:
        sess["authed"] = True
        sess["epoch"] = client.application.config["AUTH_EPOCH"]
        sess["last_seen"] = time.time()
    return client


@pytest.fixture
def csrf_authed_client(csrf_client):
    """Same idea as authed_client, but with CSRF still enabled."""
    import time
    with csrf_client.session_transaction() as sess:
        sess["authed"] = True
        sess["epoch"] = csrf_client.application.config["AUTH_EPOCH"]
        sess["last_seen"] = time.time()
    return csrf_client


@pytest.fixture
def db_session(app):
    """Yield a SQLAlchemy session bound to the test app's engine.

    Operates inside a Flask app context so flexlog.db.get_db() works for
    callers that prefer the production helper.
    """
    from flexlog.db import close_db, get_db

    with app.app_context():
        session = get_db()
        try:
            yield session
        finally:
            close_db()
