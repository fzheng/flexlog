"""Unit tests for the SQLCipher-backed SQLAlchemy engine."""
from __future__ import annotations

import os

import pytest

# Import models so Base.metadata is populated for create_all() in tests below.
from flexlog.db import models as _models  # noqa: F401


def test_make_engine_creates_encrypted_db(tmp_path):
    from flexlog.db import Base, make_engine
    key_hex = os.urandom(32).hex()
    db_path = tmp_path / "test.db"
    engine = make_engine(db_path, key_hex)
    Base.metadata.create_all(engine)
    # First 16 bytes of an encrypted SQLCipher v4 DB are NOT the plaintext magic
    head = db_path.read_bytes()[:16]
    assert head != b"SQLite format 3\x00"
    assert len(head) == 16


def test_make_engine_with_wrong_key_raises(tmp_path):
    """Opening a SQLCipher DB with the wrong key raises (on first query)."""
    from flexlog.db import Base, make_engine
    key_hex = os.urandom(32).hex()
    db_path = tmp_path / "test.db"
    engine = make_engine(db_path, key_hex)
    Base.metadata.create_all(engine)
    engine.dispose()

    wrong_engine = make_engine(db_path, os.urandom(32).hex())
    from sqlalchemy import text
    with pytest.raises(Exception):
        with wrong_engine.connect() as conn:
            conn.execute(text("SELECT name FROM sqlite_master")).fetchall()


def test_make_engine_with_same_key_roundtrips(tmp_path):
    from flexlog.db import Base, make_engine, make_session_factory
    from flexlog.db.models import Person
    import uuid
    key_hex = os.urandom(32).hex()
    db_path = tmp_path / "test.db"

    engine1 = make_engine(db_path, key_hex)
    Base.metadata.create_all(engine1)
    factory1 = make_session_factory(engine1)
    with factory1() as sess:
        sess.add(Person(id=str(uuid.uuid4()), alias="Alice"))
        sess.commit()
    engine1.dispose()

    engine2 = make_engine(db_path, key_hex)
    factory2 = make_session_factory(engine2)
    with factory2() as sess:
        names = [p.alias for p in sess.query(Person).all()]
    assert names == ["Alice"]


def test_engine_enables_foreign_keys(tmp_path):
    from flexlog.db import make_engine
    from sqlalchemy import text
    key_hex = os.urandom(32).hex()
    db_path = tmp_path / "test.db"
    engine = make_engine(db_path, key_hex)
    with engine.connect() as conn:
        row = conn.execute(text("PRAGMA foreign_keys")).fetchone()
    assert row[0] == 1
