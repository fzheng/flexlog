"""Shared pytest fixtures for flexlog tests (v0.2.0 — encrypted at rest)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from flexlog.config_loader import DEFAULT_CONFIG_JSON
from flexlog.crypto import (
    ARGON2_DEFAULT_PARAMS, aes_gcm_wrap, argon2id_kek, hkdf_subkey,
)
from flexlog.kdf_params import KdfParams, write_kdf_params

_FIXTURE_PASSWORD = "hunter2-test"  # tests use this; never used in production


@pytest.fixture
def tmp_data_dir_no_config(tmp_path, monkeypatch):
    """An existing, writable data dir with NO config.json yet, NO encryption set up."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def tmp_data_dir_no_encryption(tmp_path, monkeypatch):
    """Data dir with config.json but encryption NOT yet set up.
    Used by setup/recover tests."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
    return tmp_path


def _bootstrap_encrypted_dir(tmp_path: Path) -> bytes:
    """Set up a data dir as if a user had just done 'set password' with the
    fixture password. Returns the master key bytes for tests that need them."""
    (tmp_path / "config.json").write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")

    kek_salt = os.urandom(16)
    kek_nonce = os.urandom(12)
    master_key = os.urandom(32)
    kek = argon2id_kek(_FIXTURE_PASSWORD, kek_salt, ARGON2_DEFAULT_PARAMS)
    wrapped = aes_gcm_wrap(kek, kek_nonce, master_key)
    write_kdf_params(
        tmp_path / "kdf_params.json",
        KdfParams(
            version=1, kek_salt=kek_salt, kek_nonce=kek_nonce,
            wrapped_master_key=wrapped,
            argon2_time=ARGON2_DEFAULT_PARAMS.time_cost,
            argon2_memory_kib=ARGON2_DEFAULT_PARAMS.memory_kib,
            argon2_parallelism=ARGON2_DEFAULT_PARAMS.parallelism,
        ),
    )

    # Build the encrypted DB with schema + auth row
    from flexlog.db import Base, make_engine, make_session_factory
    sqlcipher_key = hkdf_subkey(master_key, b"flexlog/sqlcipher/v1", 32).hex()
    db_path = tmp_path / "data" / "encounters.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(db_path, sqlcipher_key)
    Base.metadata.create_all(engine)
    from sqlalchemy import text
    import secrets
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS auth (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                created_at TEXT NOT NULL,
                rotated_at TEXT NOT NULL,
                master_key_id TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            INSERT INTO auth (id, created_at, rotated_at, master_key_id)
            VALUES (1, :now, :now, :mkid)
        """), {"now": now, "mkid": secrets.token_hex(16)})
    engine.dispose()
    return master_key


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Data dir with config.json AND encryption bootstrapped with fixture password.

    Most tests use this. Tests of the setup flow itself use
    tmp_data_dir_no_encryption."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    _bootstrap_encrypted_dir(tmp_path)
    return tmp_path


@pytest.fixture
def admin_password() -> str:
    return _FIXTURE_PASSWORD


@pytest.fixture
def app(tmp_data_dir):
    """App with CSRF DISABLED. Engine + master key attached as if user logged in."""
    from flexlog.app import create_app
    from flexlog.crypto import argon2id_kek, aes_gcm_unwrap, hkdf_subkey, Argon2Params
    from flexlog.db import attach_engine_at_runtime, make_engine, make_session_factory
    from flexlog.kdf_params import load_kdf_params

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    # Mimic the post-login state: unwrap the master key + attach engine.
    kdf = load_kdf_params(tmp_data_dir / "kdf_params.json")
    params = Argon2Params(kdf.argon2_time, kdf.argon2_memory_kib, kdf.argon2_parallelism)
    kek = argon2id_kek(_FIXTURE_PASSWORD, kdf.kek_salt, params)
    master_key = aes_gcm_unwrap(kek, kdf.kek_nonce, kdf.wrapped_master_key)
    flask_app.config["MASTER_KEY"] = master_key

    sqlcipher_key = hkdf_subkey(master_key, b"flexlog/sqlcipher/v1", 32).hex()
    engine = make_engine(tmp_data_dir / "data" / "encounters.db", sqlcipher_key)
    factory = make_session_factory(engine)
    attach_engine_at_runtime(flask_app, engine, factory)

    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_app(tmp_data_dir):
    """Same as `app` but with CSRF enabled."""
    from flexlog.app import create_app
    from flexlog.crypto import argon2id_kek, aes_gcm_unwrap, hkdf_subkey, Argon2Params
    from flexlog.db import attach_engine_at_runtime, make_engine, make_session_factory
    from flexlog.kdf_params import load_kdf_params

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    # WTF_CSRF_ENABLED stays True

    kdf = load_kdf_params(tmp_data_dir / "kdf_params.json")
    params = Argon2Params(kdf.argon2_time, kdf.argon2_memory_kib, kdf.argon2_parallelism)
    kek = argon2id_kek(_FIXTURE_PASSWORD, kdf.kek_salt, params)
    master_key = aes_gcm_unwrap(kek, kdf.kek_nonce, kdf.wrapped_master_key)
    flask_app.config["MASTER_KEY"] = master_key

    sqlcipher_key = hkdf_subkey(master_key, b"flexlog/sqlcipher/v1", 32).hex()
    engine = make_engine(tmp_data_dir / "data" / "encounters.db", sqlcipher_key)
    factory = make_session_factory(engine)
    attach_engine_at_runtime(flask_app, engine, factory)

    return flask_app


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


@pytest.fixture
def authed_client(client):
    """Like `client` but with the auth session pre-populated (bypass login POST)."""
    import time
    with client.session_transaction() as sess:
        sess["authed"] = True
        sess["epoch"] = client.application.config["AUTH_EPOCH"]
        sess["last_seen"] = time.time()
    return client


@pytest.fixture
def csrf_authed_client(csrf_client):
    import time
    with csrf_client.session_transaction() as sess:
        sess["authed"] = True
        sess["epoch"] = csrf_client.application.config["AUTH_EPOCH"]
        sess["last_seen"] = time.time()
    return csrf_client


@pytest.fixture
def db_session(app):
    from flexlog.db import close_db, get_db
    with app.app_context():
        session = get_db()
        try:
            yield session
        finally:
            close_db()
