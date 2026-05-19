"""Shared pytest fixtures for flexlog tests (v0.2.0 — encrypted at rest)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from flexlog.config_loader import DEFAULT_CONFIG_JSON
from flexlog.crypto import (
    ARGON2_DEFAULT_PARAMS, Argon2Params, aes_gcm_wrap, argon2id_kek, hkdf_subkey,
)
from flexlog.kdf_params import KdfParams, write_kdf_params

_FIXTURE_PASSWORD = "hunter2-test"  # tests use this; never used in production


# ───────────────────────────────────────────────────────────────────────
# Session-wide safety net: strip FLEXLOG_DATA_DIR from the env so a
# test that forgets to monkeypatch can't accidentally touch the user's
# real data dir. Restore at session end so the shell that invoked
# `make test` doesn't lose its env var.
#
# Background: every test fixture that needs the env var sets it via
# `monkeypatch.setenv(...)`, which is per-test and auto-reverts on
# teardown. But if `FLEXLOG_DATA_DIR=$HOME/flexlog-data` is set in the
# developer's shell BEFORE pytest starts, any test code path that
# doesn't go through a fixture inherits that prod value. A
# `create_app()` call would then read prod config, attach an engine
# against prod, and any write — even a "test" upload through the real
# pipeline — would land in prod's encrypted media tree.
#
# This fixture removes that risk class entirely.
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _isolate_from_prod_data_dir():
    """Pop FLEXLOG_DATA_DIR for the session; restore on exit."""
    saved = os.environ.pop("FLEXLOG_DATA_DIR", None)
    if saved:
        looks_real = (Path(saved) / "kdf_params.json").exists()
        if looks_real:
            print(
                f"\n  flexlog test isolation: FLEXLOG_DATA_DIR was set to\n"
                f"  {saved}\n"
                f"  which contains a kdf_params.json (looks like a real\n"
                f"  data dir). It has been temporarily removed from the\n"
                f"  env for the test session. Tests use per-test tmp dirs\n"
                f"  via the `tmp_data_dir` fixture; the original value\n"
                f"  will be restored when the session ends.\n",
                file=sys.stderr,
            )
        else:
            # Even if the dir doesn't have a kdf_params.json (so isn't
            # obviously "prod"), strip it for the session — defense in
            # depth.
            pass
    yield
    if saved is not None:
        os.environ["FLEXLOG_DATA_DIR"] = saved


@pytest.fixture(autouse=True)
def _no_prod_env_leak():
    """Per-test: assert no fixture left FLEXLOG_DATA_DIR pointing at a
    suspicious directory. monkeypatch.setenv already reverts after each
    test, so by the time this fixture's teardown runs the env should
    be clean. If it isn't, a test mutated `os.environ` directly
    (bypassing monkeypatch) and that's a bug.

    The check fires after the test body and before the next test starts,
    so a regression surfaces immediately rather than as a hard-to-trace
    cross-test interaction."""
    yield
    val = os.environ.get("FLEXLOG_DATA_DIR")
    if val is None:
        return
    p = Path(val)
    if (p / "kdf_params.json").exists():
        raise AssertionError(
            f"Test left FLEXLOG_DATA_DIR={val!r} pointing at a real "
            f"data dir (kdf_params.json exists there). Use "
            f"monkeypatch.setenv(...) instead of os.environ[...] = "
            f"so the value auto-reverts."
        )

# Argon2id with production params (~500ms each) makes the fixture-heavy
# suite take ~45s. For tests we run hundreds of fixtures per session and
# the cryptographic correctness doesn't depend on the cost parameters —
# only KDF correctness does. Use a near-minimal cost so the suite stays
# under 10s. The Argon2 RFC requires time_cost >= 1, memory_cost >= 8.
_FIXTURE_ARGON2_PARAMS = Argon2Params(time_cost=1, memory_kib=8, parallelism=1)


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
    kek = argon2id_kek(_FIXTURE_PASSWORD, kek_salt, _FIXTURE_ARGON2_PARAMS)
    wrapped = aes_gcm_wrap(kek, kek_nonce, master_key)
    write_kdf_params(
        tmp_path / "kdf_params.json",
        KdfParams(
            version=1, kek_salt=kek_salt, kek_nonce=kek_nonce,
            wrapped_master_key=wrapped,
            argon2_time=_FIXTURE_ARGON2_PARAMS.time_cost,
            argon2_memory_kib=_FIXTURE_ARGON2_PARAMS.memory_kib,
            argon2_parallelism=_FIXTURE_ARGON2_PARAMS.parallelism,
        ),
    )

    # Build the encrypted DB with schema
    from flexlog.db import Base, make_engine, make_session_factory
    import flexlog.db.models as _models  # noqa: F401 — registers ORM tables with Base
    sqlcipher_key = hkdf_subkey(master_key, b"flexlog/sqlcipher/v1", 32).hex()
    db_path = tmp_path / "data" / "encounters.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(db_path, sqlcipher_key)
    Base.metadata.create_all(engine)
    from sqlalchemy import text
    # Stamp the user_version so the v1→v2 migration is a no-op on the
    # fresh v2-shaped fixture DB.
    with engine.begin() as conn:
        conn.execute(text("PRAGMA user_version = 2"))
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


@pytest.fixture
def person(db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Test", tag_input="")
    db_session.commit()
    return p


@pytest.fixture
def csrf_db_session(csrf_app):
    from flexlog.db import close_db, get_db
    with csrf_app.app_context():
        s = get_db()
        try:
            yield s
        finally:
            close_db()


@pytest.fixture
def csrf_person(csrf_db_session):
    from flexlog.services.people import create_person
    p = create_person(csrf_db_session, alias="Test", tag_input="")
    csrf_db_session.commit()
    return p
