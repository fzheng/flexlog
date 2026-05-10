"""Database engine + session factory for flexlog.

The engine is SQLCipher-backed: every page on disk is encrypted with
AES-256-CBC + HMAC-SHA512 under a 32-byte key derived from the user's
master key via HKDF. The key is passed as a hex string at connection
time via `PRAGMA key`.

Models live in flexlog.db.models. The engine is created AT LOGIN
(when the master key is unwrapped), not at app boot — anonymous routes
never touch the DB.
"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, current_app, g
from sqlalchemy import Engine, create_engine, event, pool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all flexlog ORM models."""


def make_engine(db_path: Path, sqlcipher_key_hex: str) -> Engine:
    """Create a SQLAlchemy engine pointed at a SQLCipher-encrypted SQLite DB.

    `sqlcipher_key_hex` must be 64 hex chars (32 bytes). It's applied via
    `PRAGMA key = "x'<hex>'"` on every new connection.

    Uses StaticPool (single connection re-used) since flexlog is
    single-user and we want every request to see the same key-set
    connection — and we want to avoid the per-connect Argon2id-equivalent
    cost SQLCipher imposes on opening a fresh handle.
    """
    if len(sqlcipher_key_hex) != 64:
        raise ValueError(
            f"sqlcipher_key_hex must be 64 hex chars; got {len(sqlcipher_key_hex)}"
        )

    from sqlcipher3 import dbapi2 as sqlcipher_dbapi

    engine = create_engine(
        f"sqlite:///{db_path}",
        module=sqlcipher_dbapi,
        connect_args={"check_same_thread": False},
        poolclass=pool.StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_key_and_fk(dbapi_conn, _connection_record):
        cur = dbapi_conn.cursor()
        cur.execute(f"PRAGMA key = \"x'{sqlcipher_key_hex}'\"")
        cur.execute("PRAGMA cipher_compatibility = 4")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to `engine`. Each `Session()` is independent."""
    return sessionmaker(bind=engine, expire_on_commit=True, future=True)


_SESSION_KEY = "_flexlog_db_session"
_FACTORY_KEY = "FLEXLOG_DB_SESSION_FACTORY"
_ENGINE_KEY = "FLEXLOG_DB_ENGINE"


def attach_to_app(app: Flask, engine: Engine, session_factory: sessionmaker[Session]) -> None:
    """Stash engine + session factory on the Flask app and register teardown."""
    app.config[_ENGINE_KEY] = engine
    app.config[_FACTORY_KEY] = session_factory

    @app.teardown_appcontext
    def _close(_error: BaseException | None) -> None:
        close_db()


def attach_engine_at_runtime(app: Flask, engine: Engine,
                              session_factory: sessionmaker[Session]) -> None:
    """Swap a fresh engine + factory into the app config AFTER login.

    Dispose any existing engine first (closes its pooled connections)."""
    old = app.config.get(_ENGINE_KEY)
    if old is not None and old is not engine:
        try:
            old.dispose()
        except Exception:
            pass
    app.config[_ENGINE_KEY] = engine
    app.config[_FACTORY_KEY] = session_factory


def get_db() -> Session:
    """Return the request-scoped Session, creating it on first call.

    Must be called inside a Flask app context. The session is closed by the
    teardown handler installed in `attach_to_app`.

    Raises RuntimeError if no engine has been attached yet (i.e. the user
    is on the login page and hasn't authenticated)."""
    if _FACTORY_KEY not in current_app.config:
        raise RuntimeError(
            "no DB engine attached; the user must log in before any DB "
            "operation can run"
        )
    if _SESSION_KEY not in g:
        factory = current_app.config[_FACTORY_KEY]
        g.setdefault(_SESSION_KEY, factory())
    return g.get(_SESSION_KEY)


def close_db() -> None:
    """Close + remove the request-scoped Session if one was created."""
    session = g.pop(_SESSION_KEY, None)
    if session is not None:
        session.close()
