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

    Uses SingletonThreadPool (one connection per worker thread) so
    Flask's threaded=True server can serve concurrent requests without
    cross-thread sharing of a single DBAPI connection. Each thread pays
    the PRAGMA key cost once on its first DB touch; the cost is small
    (<10 ms) compared with the typical request latency.
    """
    if len(sqlcipher_key_hex) != 64:
        raise ValueError(
            f"sqlcipher_key_hex must be 64 hex chars; got {len(sqlcipher_key_hex)}"
        )

    from sqlcipher3 import dbapi2 as sqlcipher_dbapi

    engine = create_engine(
        f"sqlite:///{db_path}",
        module=sqlcipher_dbapi,
        # NullPool: every request opens a fresh DBAPI connection in its
        # handler thread and closes it in the same thread. Two reasons we
        # don't pool:
        # 1. SQLCipher's underlying SQLite isn't fully thread-safe at the C
        #    level on common builds; any pool that retains connections
        #    across threads risks C-level crashes (segfaults) when
        #    check_same_thread=False is set to silence the Python guard.
        # 2. SingletonThreadPool produced noisy "thread can only be used
        #    in that same thread" errors at dispose time, because dying
        #    request threads leave behind connections that the pool's
        #    cleanup tries to close from a different thread.
        # NullPool avoids both: no retention, no cross-thread close. Cost
        # is one PRAGMA key per request, which is microseconds because we
        # pass the raw key (x'...' syntax) without PBKDF2 derivation.
        connect_args={"check_same_thread": True},
        poolclass=pool.NullPool,
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


def register_db_teardown(app: Flask) -> None:
    """Register the appcontext teardown that closes the per-request DB
    session. Called once at app-factory time, before any engine is
    attached. The teardown is safe to fire on every request — `close_db`
    pops nothing when no session was opened (e.g. anonymous routes).
    """
    @app.teardown_appcontext
    def _close(_error: BaseException | None) -> None:
        close_db()


def attach_to_app(app: Flask, engine: Engine, session_factory: sessionmaker[Session]) -> None:
    """Stash engine + session factory on the Flask app.

    The session-close teardown must be registered separately via
    `register_db_teardown(app)` at app-factory time (it's idempotent across
    engine swaps, so we don't re-register on every attach)."""
    app.config[_ENGINE_KEY] = engine
    app.config[_FACTORY_KEY] = session_factory


def attach_engine_at_runtime(app: Flask, engine: Engine,
                              session_factory: sessionmaker[Session]) -> None:
    """Swap a fresh engine + factory into the app config AFTER login.

    Dispose any existing engine first (closes its pooled connections).
    Assumes `register_db_teardown(app)` was already called at app-factory
    time so per-request sessions get closed by Flask's teardown hook.
    After attaching, runs any pending schema migrations on the new engine
    so post-login code never observes a stale schema."""
    old = app.config.get(_ENGINE_KEY)
    if old is not None and old is not engine:
        try:
            old.dispose()
        except Exception:
            pass
    app.config[_ENGINE_KEY] = engine
    app.config[_FACTORY_KEY] = session_factory

    # Local import — flexlog.migrations imports SQLAlchemy at module top,
    # which is fine, but the migration module imports `text` which is already
    # imported here. Keeping the import local makes the dependency direction
    # one-way (db doesn't depend on migrations at import time).
    from flexlog.migrations.v1_to_v2 import migrate_to_latest
    migrate_to_latest(engine)


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
