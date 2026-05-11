"""v1 → v2 schema migration: drop overall_score, rename
custom_ratings_json → ratings_json, merge overall_score into
the JSON under the stable key 'overall_score'."""
from __future__ import annotations

import json

from sqlalchemy import text

from flexlog.migrations.v1_to_v2 import migrate_v1_to_v2


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
