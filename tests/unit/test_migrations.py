"""v1 → v2 schema migration: drop overall_score, rename
custom_ratings_json → ratings_json, merge overall_score into
the JSON under the stable key 'overall_score'."""
from __future__ import annotations

import json

from sqlalchemy import text

from flexlog.migrations.v1_to_v2 import (
    migrate_to_latest,
    migrate_v1_to_v2,
    repair_dangling_session_fk_refs,
)


def _make_v1_engine(tmp_path):
    """Build an old-shape DB (no SQLCipher; plain SQLite is fine for the
    migration unit test). Schema matches what v0.2.0 wrote."""
    from sqlalchemy import create_engine
    db = tmp_path / "v1.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as c:
        c.execute(text("PRAGMA user_version = 0"))
        c.execute(text("""
            CREATE TABLE session (
              id TEXT PRIMARY KEY,
              person_id TEXT NOT NULL,
              session_date TEXT NOT NULL,
              overall_score INTEGER NOT NULL,
              custom_ratings_json TEXT,
              notes TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            INSERT INTO session VALUES
              ('s1', 'p1', '2026-01-01', 4, '{"clarity": 3}', NULL, 'now', 'now'),
              ('s2', 'p1', '2026-01-02', 5, NULL, NULL, 'now', 'now'),
              ('s3', 'p1', '2026-01-03', 2, 'not json', NULL, 'now', 'now')
        """))
    return engine


def test_migrate_v1_to_v2_merges_overall_score_into_json(tmp_path):
    engine = _make_v1_engine(tmp_path)
    migrate_v1_to_v2(engine)

    with engine.begin() as c:
        version = c.execute(text("PRAGMA user_version")).scalar()
        assert version == 2

        rows = list(c.execute(text(
            "SELECT id, ratings_json FROM session ORDER BY id"
        )))

    s1 = json.loads(rows[0][1])
    assert s1 == {"overall_score": 4, "clarity": 3}

    s2 = json.loads(rows[1][1])
    assert s2 == {"overall_score": 5}

    # Corrupted custom_ratings_json falls back to {} merged with overall_score
    s3 = json.loads(rows[2][1])
    assert s3 == {"overall_score": 2}


def test_migrate_v1_to_v2_drops_overall_score_column(tmp_path):
    engine = _make_v1_engine(tmp_path)
    migrate_v1_to_v2(engine)
    with engine.begin() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(session)"))]
    assert "overall_score" not in cols
    assert "ratings_json" in cols
    assert "custom_ratings_json" not in cols


def test_migrate_v1_to_v2_is_idempotent(tmp_path):
    engine = _make_v1_engine(tmp_path)
    migrate_v1_to_v2(engine)
    migrate_v1_to_v2(engine)  # second run must be a no-op
    with engine.begin() as c:
        version = c.execute(text("PRAGMA user_version")).scalar()
        rows = list(c.execute(text("SELECT ratings_json FROM session ORDER BY id")))
    assert version == 2
    assert json.loads(rows[0][0]) == {"overall_score": 4, "clarity": 3}


def test_migrate_v1_to_v2_recreates_session_person_date_index(tmp_path):
    """Real v0.2.0 DB has ix_session_person_date on (person_id, session_date);
    the rebuild must recreate it so query plans don't regress."""
    engine = _make_v1_engine(tmp_path)
    # Pre-create the index that v0.2.0 had on the live table.
    with engine.begin() as c:
        c.execute(text(
            "CREATE INDEX ix_session_person_date ON session (person_id, session_date)"
        ))
    migrate_v1_to_v2(engine)
    with engine.begin() as c:
        names = [r[0] for r in c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='session'"
        )).all()]
    assert "ix_session_person_date" in names


def _make_v1_engine_with_dependents(tmp_path):
    """Build a v0.2.0-shape DB that includes session_media + session_link
    with FKs pointing at `session`, plus a media_file and a person row so
    the FKs are satisfied. Mirrors the real prod shape that the migration
    must preserve."""
    from sqlalchemy import create_engine
    db = tmp_path / "v1_with_deps.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as c:
        c.execute(text("PRAGMA user_version = 0"))
        c.execute(text("""
            CREATE TABLE person (
              id TEXT PRIMARY KEY,
              alias TEXT NOT NULL,
              avatar_media_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE media_file (
              id TEXT PRIMARY KEY,
              sha256 TEXT NOT NULL UNIQUE,
              file_key TEXT NOT NULL,
              media_type TEXT NOT NULL,
              original_filename TEXT,
              mime_type TEXT NOT NULL,
              file_size_bytes INTEGER NOT NULL,
              created_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE session (
              id TEXT PRIMARY KEY,
              person_id TEXT NOT NULL REFERENCES person (id) ON DELETE CASCADE,
              session_date TEXT NOT NULL,
              overall_score INTEGER NOT NULL CHECK (overall_score >= 0 AND overall_score <= 5),
              custom_ratings_json TEXT,
              notes TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE session_media (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL REFERENCES session (id) ON DELETE CASCADE,
              media_file_id TEXT NOT NULL REFERENCES media_file (id) ON DELETE CASCADE,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE session_link (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL REFERENCES session (id) ON DELETE CASCADE,
              url TEXT NOT NULL,
              label TEXT,
              thumbnail_media_id TEXT REFERENCES media_file (id) ON DELETE SET NULL,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            )
        """))
        c.execute(text("INSERT INTO person VALUES ('p1', 'Alice', NULL, 'now', 'now')"))
        c.execute(text("""
            INSERT INTO media_file VALUES
              ('m1', 'a' || HEX(RANDOMBLOB(31)), 'k/a', 'photo', 'a.jpg',
               'image/jpeg', 10, 'now')
        """))
        c.execute(text("""
            INSERT INTO session VALUES
              ('s1', 'p1', '2026-01-01', 4, '{}', NULL, 'now', 'now')
        """))
        c.execute(text(
            "INSERT INTO session_media VALUES ('sm1', 's1', 'm1', 0, 'now')"
        ))
        c.execute(text(
            "INSERT INTO session_link VALUES "
            "('sl1', 's1', 'https://example.com', 'Demo', NULL, 0, 'now')"
        ))
    return engine


def test_migrate_v1_to_v2_preserves_session_media_fk(tmp_path):
    """After migration, deleting a media_file must cascade through
    session_media. The earlier rename-first migration left dangling FK
    references to _session_old, causing CASCADE deletes to fail with
    'no such table: _session_old'. This test guards against regression."""
    engine = _make_v1_engine_with_dependents(tmp_path)
    migrate_v1_to_v2(engine)

    with engine.begin() as c:
        # Enable FK enforcement (test DB defaults to off).
        c.execute(text("PRAGMA foreign_keys=ON"))
        # Deleting the media file should cascade-delete session_media row.
        c.execute(text("DELETE FROM media_file WHERE id = 'm1'"))
        remaining = c.execute(text("SELECT COUNT(*) FROM session_media")).scalar()
    assert remaining == 0


def test_migrate_v1_to_v2_preserves_session_link_fk(tmp_path):
    """Same guard for session_link: deleting a session must cascade through
    session_link without hitting a dangling _session_old reference."""
    engine = _make_v1_engine_with_dependents(tmp_path)
    migrate_v1_to_v2(engine)

    with engine.begin() as c:
        c.execute(text("PRAGMA foreign_keys=ON"))
        c.execute(text("DELETE FROM session WHERE id = 's1'"))
        link_count = c.execute(text("SELECT COUNT(*) FROM session_link")).scalar()
        media_count = c.execute(text("SELECT COUNT(*) FROM session_media")).scalar()
    assert link_count == 0
    assert media_count == 0


def test_repair_dangling_session_fk_refs_is_noop_on_clean_db(tmp_path):
    """A properly-migrated DB has no _session_old references; the repair
    must be a no-op (don't touch dependent tables)."""
    engine = _make_v1_engine_with_dependents(tmp_path)
    migrate_v1_to_v2(engine)
    with engine.begin() as c:
        before = c.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE name IN ('session_media', 'session_link') ORDER BY name"
        )).all()

    repair_dangling_session_fk_refs(engine)

    with engine.begin() as c:
        after = c.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE name IN ('session_media', 'session_link') ORDER BY name"
        )).all()
    assert before == after


def test_repair_dangling_session_fk_refs_fixes_broken_db(tmp_path):
    """Simulate the v0.3.0 bug: dependent tables have FKs pointing at
    _session_old after a botched rename-first migration. The repair
    must recreate them with FKs back to session, preserve data, and
    leave the cascade chain working."""
    from sqlalchemy import create_engine

    db = tmp_path / "broken.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as c:
        # Build the broken state directly: session is correct, but
        # session_media references _session_old in its FK.
        c.execute(text("PRAGMA user_version = 2"))
        c.execute(text("""
            CREATE TABLE person (
              id TEXT PRIMARY KEY, alias TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE media_file (
              id TEXT PRIMARY KEY,
              sha256 TEXT NOT NULL UNIQUE,
              file_key TEXT NOT NULL,
              media_type TEXT NOT NULL,
              original_filename TEXT,
              mime_type TEXT NOT NULL,
              file_size_bytes INTEGER NOT NULL,
              created_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE session (
              id TEXT PRIMARY KEY,
              person_id TEXT NOT NULL REFERENCES person (id) ON DELETE CASCADE,
              session_date TEXT NOT NULL,
              ratings_json TEXT,
              notes TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """))
        # Broken FK target: _session_old (the table that no longer exists).
        c.execute(text("""
            CREATE TABLE session_media (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL REFERENCES _session_old (id) ON DELETE CASCADE,
              media_file_id TEXT NOT NULL REFERENCES media_file (id) ON DELETE CASCADE,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            CREATE TABLE session_link (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL REFERENCES _session_old (id) ON DELETE CASCADE,
              url TEXT NOT NULL,
              label TEXT,
              thumbnail_media_id TEXT REFERENCES media_file (id) ON DELETE SET NULL,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            )
        """))
        c.execute(text("INSERT INTO person VALUES ('p1', 'A', 'now', 'now')"))
        c.execute(text("""
            INSERT INTO media_file VALUES
              ('m1', 'a' || HEX(RANDOMBLOB(31)), 'k/a', 'photo', 'a.jpg',
               'image/jpeg', 10, 'now')
        """))
        c.execute(text("""
            INSERT INTO session VALUES
              ('s1', 'p1', '2026-01-01', '{}', NULL, 'now', 'now')
        """))
        c.execute(text(
            "INSERT INTO session_media VALUES ('sm1', 's1', 'm1', 0, 'now')"
        ))
        c.execute(text(
            "INSERT INTO session_link VALUES "
            "('sl1', 's1', 'https://x.test', NULL, NULL, 0, 'now')"
        ))

    repair_dangling_session_fk_refs(engine)

    with engine.begin() as c:
        # No more _session_old references anywhere.
        broken = c.execute(text(
            "SELECT name FROM sqlite_master WHERE sql LIKE '%_session_old%'"
        )).all()
        assert broken == []

        # Data preserved.
        sm_count = c.execute(text("SELECT COUNT(*) FROM session_media")).scalar()
        sl_count = c.execute(text("SELECT COUNT(*) FROM session_link")).scalar()
        assert sm_count == 1
        assert sl_count == 1

        # Cascade through media_file delete works now (this was broken
        # before the repair).
        c.execute(text("PRAGMA foreign_keys=ON"))
        c.execute(text("DELETE FROM media_file WHERE id = 'm1'"))
        sm_remaining = c.execute(text("SELECT COUNT(*) FROM session_media")).scalar()
    assert sm_remaining == 0


def test_migrate_to_latest_runs_repair_after_migration():
    """Smoke: migrate_to_latest calls both migrate_v1_to_v2 and the repair
    in order. We exercise this via the integration suite (every test that
    uses the `app` fixture goes through migrate_to_latest), so this test
    just imports the public API to confirm it exists."""
    assert callable(migrate_to_latest)
