from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from flexlog.db import Base, make_engine, make_session_factory


def test_make_engine_creates_sqlite_file_lazily(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    # Engine creation does NOT touch the filesystem until a connection opens.
    # But once we connect, the file appears.
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert db_path.exists()


def test_make_engine_enables_foreign_keys(tmp_path):
    """SQLite ignores ON DELETE CASCADE unless PRAGMA foreign_keys=ON."""
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "foreign_keys pragma must be ON"


def test_make_session_factory_yields_working_sessions(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Session = make_session_factory(engine)
    with Session() as session:
        # Sessions can execute trivial queries
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_base_metadata_is_a_metadata_object(tmp_path):
    """Sanity: Base must expose .metadata for create_all() in app factory."""
    assert hasattr(Base, "metadata")
    # Should have a `create_all` callable
    assert callable(Base.metadata.create_all)
