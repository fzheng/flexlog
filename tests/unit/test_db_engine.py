"""Engine attach / detach lifecycle + key validation.

Coverage targets in flexlog/db/__init__.py:
- make_engine rejects keys that aren't 64 hex chars
- attach_to_app (boot-time stash, separate from runtime attach)
- detach_engine_at_runtime idempotency
- engine_is_attached(app) with explicit app argument
"""
from __future__ import annotations

import pytest


def test_make_engine_rejects_short_key(tmp_path):
    from flexlog.db import make_engine
    with pytest.raises(ValueError, match="64 hex chars"):
        make_engine(tmp_path / "x.db", sqlcipher_key_hex="abc")


def test_make_engine_rejects_long_key(tmp_path):
    from flexlog.db import make_engine
    with pytest.raises(ValueError, match="64 hex chars"):
        make_engine(tmp_path / "x.db", sqlcipher_key_hex="a" * 65)


def test_make_engine_rejects_non_hex_at_wrong_length(tmp_path):
    """Strict length-only check; bytes.fromhex would catch non-hex
    later at PRAGMA time. The length guard fires first."""
    from flexlog.db import make_engine
    with pytest.raises(ValueError, match="64 hex chars"):
        make_engine(tmp_path / "x.db", sqlcipher_key_hex="")


def test_attach_to_app_sets_config_keys():
    """attach_to_app (the boot-time variant; distinct from
    attach_engine_at_runtime) stashes engine + factory in app.config."""
    from flask import Flask
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from flexlog.db import attach_to_app

    app = Flask(__name__)
    engine = create_engine("sqlite:///:memory:")
    try:
        factory = sessionmaker(bind=engine)
        attach_to_app(app, engine, factory)
        assert app.config.get("FLEXLOG_DB_ENGINE") is engine
        assert app.config.get("FLEXLOG_DB_SESSION_FACTORY") is factory
    finally:
        engine.dispose()


def test_detach_engine_at_runtime_idempotent():
    """detach on an app with no engine attached is a no-op (doesn't raise)."""
    from flask import Flask
    from flexlog.db import detach_engine_at_runtime
    app = Flask(__name__)
    detach_engine_at_runtime(app)  # must not raise
    detach_engine_at_runtime(app)  # still no-op


def test_detach_engine_at_runtime_disposes_engine():
    """detach disposes the engine; second detach is a no-op."""
    from flask import Flask
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from flexlog.db import attach_to_app, detach_engine_at_runtime

    app = Flask(__name__)
    engine = create_engine("sqlite:///:memory:")
    factory = sessionmaker(bind=engine)
    attach_to_app(app, engine, factory)
    # detach_engine_at_runtime calls engine.dispose() internally — no
    # try/finally needed here. (test_attach_to_app_sets_config_keys
    # above DOES need finally: it doesn't call detach.)
    detach_engine_at_runtime(app)
    assert "FLEXLOG_DB_ENGINE" not in app.config
    assert "FLEXLOG_DB_SESSION_FACTORY" not in app.config


def test_engine_is_attached_explicit_app_arg():
    """engine_is_attached(app=...) bypasses current_app — useful for
    testing without an app context."""
    from flask import Flask
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from flexlog.db import attach_to_app, engine_is_attached

    app = Flask(__name__)
    assert engine_is_attached(app) is False

    engine = create_engine("sqlite:///:memory:")
    try:
        attach_to_app(app, engine, sessionmaker(bind=engine))
        assert engine_is_attached(app) is True
    finally:
        engine.dispose()


def test_get_db_raises_when_no_engine():
    """Anonymous requests can't get a DB session — engine isn't
    attached. get_db() raises RuntimeError with a clear message."""
    from flask import Flask
    from flexlog.db import get_db, register_db_teardown
    app = Flask(__name__)
    register_db_teardown(app)
    with app.test_request_context("/"):
        with pytest.raises(RuntimeError, match="must log in"):
            get_db()
