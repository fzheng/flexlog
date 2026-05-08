"""Database engine + session factory for flexlog.

Models live in flexlog.db.models. The engine is created from
flexlog.paths.db_path() at app-factory time; session lifecycle is
request-scoped via Flask's `g` object and the teardown handler.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, current_app, g
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all flexlog ORM models."""


def make_engine(db_path: Path) -> Engine:
    """Create the SQLite engine pointed at `db_path`.

    Enables foreign-key enforcement (SQLite has it OFF by default, which
    silently breaks ON DELETE CASCADE / SET NULL).
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_fk_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to `engine`. Each `Session()` is independent."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


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


def get_db() -> Session:
    """Return the request-scoped Session, creating it on first call.

    Must be called inside a Flask app context (i.e. during a request or
    inside `with app.app_context():`). The session is closed by the
    teardown handler installed in `attach_to_app`.
    """
    if _SESSION_KEY not in g:
        factory = current_app.config[_FACTORY_KEY]
        g.setdefault(_SESSION_KEY, factory())
    return g.get(_SESSION_KEY)


def close_db() -> None:
    """Close + remove the request-scoped Session if one was created."""
    session = g.pop(_SESSION_KEY, None)
    if session is not None:
        session.close()
