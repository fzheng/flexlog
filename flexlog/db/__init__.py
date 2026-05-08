"""Database engine + session factory for flexlog.

Models live in flexlog.db.models. The engine is created from
flexlog.paths.db_path() at app-factory time; session lifecycle is
request-scoped via Flask's `g` object and the teardown handler.
"""

from __future__ import annotations

from pathlib import Path

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
