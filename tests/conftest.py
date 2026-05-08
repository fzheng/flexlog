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
    from flexlog.app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
