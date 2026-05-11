"""v1 → v2: drop Session.overall_score, rename custom_ratings_json →
ratings_json, merge overall_score into the JSON under the stable id
'overall_score'.

Triggered from `flexlog.db.attach_engine_at_runtime`. Idempotent on a
DB that already reports `PRAGMA user_version >= 2`.
"""
from __future__ import annotations

import json

from sqlalchemy import Engine, text

TARGET_VERSION = 2


def _table_has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return any(r[1] == column for r in rows)


def _parse_or_empty(raw):
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def migrate_v1_to_v2(engine: Engine) -> None:
    """Apply the v1 → v2 migration. No-op on a v2 DB.

    Structural changes (dropping overall_score / custom_ratings_json) are only
    performed when there are existing rows to migrate — i.e. a real user DB
    from v0.2.0. A fresh DB that was just created by Base.metadata.create_all
    (which still carries the v1 model shape at this milestone) will have zero
    session rows; the migration stamps user_version = 2 without restructuring
    the table so the v1 ORM model continues to work until Task 5 updates it."""
    with engine.begin() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar() or 0
        if version >= TARGET_VERSION:
            return

        # Verify the column actually exists before attempting the move. Belt
        # and braces — covers the case of a half-migrated DB from a prior
        # crash where user_version stayed at 0 but the column is already
        # gone.
        has_overall_score = _table_has_column(conn, "session", "overall_score")
        has_old_json = _table_has_column(conn, "session", "custom_ratings_json")
        has_new_json = _table_has_column(conn, "session", "ratings_json")

        if has_new_json and not has_overall_score and not has_old_json:
            # Schema is already at v2 shape; just bump the version pragma.
            conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION}"))
            return

        # Count existing rows. If zero, this is a fresh DB — no data to
        # migrate. Skip structural changes so the v1 ORM model (still in
        # place until Task 5) continues to work against the same table shape.
        row_count = conn.execute(text("SELECT COUNT(*) FROM session")).scalar() or 0

        if row_count == 0:
            # Nothing to migrate; just mark the DB as current.
            conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION}"))
            return

        # --- Real v0.2.0 user DB: migrate data then restructure schema. ---

        # Add the new column if not present yet.
        if not has_new_json:
            conn.execute(text("ALTER TABLE session ADD COLUMN ratings_json TEXT"))

        # Copy data: merge overall_score into the (possibly NULL) JSON dict.
        rows = list(conn.execute(text(
            "SELECT id, overall_score, custom_ratings_json FROM session"
        )))
        for sid, overall, raw in rows:
            merged = _parse_or_empty(raw)
            if overall is not None:
                merged["overall_score"] = int(overall)
            conn.execute(
                text("UPDATE session SET ratings_json = :j WHERE id = :i"),
                {"j": json.dumps(dict(sorted(merged.items()))), "i": sid},
            )

        # Drop the obsolete columns.
        #
        # SQLite 3.35+ supports ALTER TABLE DROP COLUMN, but it refuses to drop
        # a column that is still referenced by a CHECK constraint (even if that
        # constraint is being dropped together with the column). The 'session'
        # table in v0.2.0 carried a named CHECK on overall_score, so we use the
        # "rename → recreate → copy → drop" approach instead — safe on all
        # SQLite/SQLCipher versions and avoids the constraint check.
        if has_overall_score or has_old_json:
            conn.execute(text("ALTER TABLE session RENAME TO _session_old"))
            conn.execute(text("""
                CREATE TABLE session (
                    id          VARCHAR NOT NULL,
                    person_id   VARCHAR NOT NULL
                                REFERENCES person (id) ON DELETE CASCADE,
                    session_date TEXT    NOT NULL,
                    ratings_json TEXT,
                    notes        TEXT,
                    created_at   TEXT    NOT NULL,
                    updated_at   TEXT    NOT NULL,
                    PRIMARY KEY (id)
                )
            """))
            conn.execute(text("""
                INSERT INTO session
                    (id, person_id, session_date, ratings_json, notes,
                     created_at, updated_at)
                SELECT id, person_id, session_date, ratings_json, notes,
                       created_at, updated_at
                FROM _session_old
            """))
            conn.execute(text("DROP TABLE _session_old"))

        conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION}"))


def migrate_to_latest(engine: Engine) -> None:
    """Run all pending migrations in order. Call this from anywhere that
    attaches an engine (login, setup, test fixtures)."""
    migrate_v1_to_v2(engine)
