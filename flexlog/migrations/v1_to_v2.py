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


class MigrationError(RuntimeError):
    """Raised when a schema migration fails. Caught by the Flask error
    handler in `flexlog.app`, which renders a friendly setup-error page
    instead of a stack trace. The original exception is the __cause__."""


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

        # Drop the obsolete columns via SQLite's canonical "create new with
        # temp name → copy → drop original → rename" pattern (from
        # https://www.sqlite.org/lang_altertable.html section 7 "Making Other
        # Kinds Of Table Schema Changes"). We can't use plain DROP COLUMN
        # because v0.2.0's `overall_score` carried a named CHECK constraint.
        #
        # CRITICAL: we do NOT use the "rename source first → create new →
        # drop renamed-source" variant. With modern SQLite (legacy_alter_table=0
        # default), ALTER TABLE RENAME auto-rewrites FK references in
        # dependent tables (session_media, session_link). Dropping the
        # renamed-away table then leaves those FK references dangling at the
        # gone _session_old, breaking any later cascade. The pattern below
        # avoids that: ALTER TABLE RENAME only fires on the temp `_session_new`,
        # which no dependent table references.
        if has_overall_score or has_old_json:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("""
                CREATE TABLE _session_new (
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
                INSERT INTO _session_new
                    (id, person_id, session_date, ratings_json, notes,
                     created_at, updated_at)
                SELECT id, person_id, session_date, ratings_json, notes,
                       created_at, updated_at
                FROM session
            """))
            conn.execute(text("DROP TABLE session"))
            conn.execute(text("ALTER TABLE _session_new RENAME TO session"))
            # Recreate the composite index that lived on the old table.
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_session_person_date "
                "ON session (person_id, session_date)"
            ))
            conn.execute(text("PRAGMA foreign_keys=ON"))

        conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION}"))


def repair_dangling_session_fk_refs(engine: Engine) -> None:
    """Detect + rebuild dependent tables whose FK references point at the
    long-gone `_session_old` (an earlier-version bug in migrate_v1_to_v2).
    Idempotent: a no-op when sqlite_master is clean.

    Affected tables: `session_media`, `session_link`. The repair recreates
    each with FK references restored to `session`, preserves all data, and
    re-creates the original indexes.
    """
    with engine.begin() as conn:
        broken = {
            row[0]
            for row in conn.execute(text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND sql LIKE '%_session_old%'"
            )).all()
        }
        if not broken:
            return

        conn.execute(text("PRAGMA foreign_keys=OFF"))

        if "session_media" in broken:
            conn.execute(text("""
                CREATE TABLE _session_media_new (
                    id            VARCHAR NOT NULL PRIMARY KEY,
                    session_id    VARCHAR NOT NULL
                                  REFERENCES session (id) ON DELETE CASCADE,
                    media_file_id VARCHAR NOT NULL
                                  REFERENCES media_file (id) ON DELETE CASCADE,
                    sort_order    INTEGER NOT NULL DEFAULT 0,
                    created_at    TEXT    NOT NULL
                )
            """))
            conn.execute(text(
                "INSERT INTO _session_media_new "
                "(id, session_id, media_file_id, sort_order, created_at) "
                "SELECT id, session_id, media_file_id, sort_order, created_at "
                "FROM session_media"
            ))
            conn.execute(text("DROP TABLE session_media"))
            conn.execute(text(
                "ALTER TABLE _session_media_new RENAME TO session_media"
            ))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_session_media_pair "
                "ON session_media (session_id, media_file_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_session_media_file "
                "ON session_media (media_file_id)"
            ))

        if "session_link" in broken:
            conn.execute(text("""
                CREATE TABLE _session_link_new (
                    id                 VARCHAR NOT NULL PRIMARY KEY,
                    session_id         VARCHAR NOT NULL
                                       REFERENCES session (id) ON DELETE CASCADE,
                    url                TEXT    NOT NULL,
                    label              TEXT,
                    thumbnail_media_id VARCHAR
                                       REFERENCES media_file (id) ON DELETE SET NULL,
                    sort_order         INTEGER NOT NULL DEFAULT 0,
                    created_at         TEXT    NOT NULL
                )
            """))
            conn.execute(text(
                "INSERT INTO _session_link_new "
                "(id, session_id, url, label, thumbnail_media_id, "
                " sort_order, created_at) "
                "SELECT id, session_id, url, label, thumbnail_media_id, "
                "       sort_order, created_at "
                "FROM session_link"
            ))
            conn.execute(text("DROP TABLE session_link"))
            conn.execute(text(
                "ALTER TABLE _session_link_new RENAME TO session_link"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_session_link_thumbnail_media "
                "ON session_link (thumbnail_media_id)"
            ))

        conn.execute(text("PRAGMA foreign_keys=ON"))


def migrate_to_latest(engine: Engine) -> None:
    """Run all pending migrations in order. Call this from anywhere that
    attaches an engine (login, setup, test fixtures).

    Any underlying exception is wrapped in `MigrationError` so the Flask
    error handler can render a friendly setup-error page rather than a
    raw 500."""
    try:
        migrate_v1_to_v2(engine)
        repair_dangling_session_fk_refs(engine)
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError(f"schema migration failed: {exc}") from exc
