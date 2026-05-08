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
    """An existing, writable data dir with the canonical default config.json."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
    return tmp_path


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
