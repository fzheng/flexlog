"""Verify that attach_engine_at_runtime triggers migrate_to_latest.

The test fixture's `app` already calls attach_engine_at_runtime, so by
the time we touch the engine, user_version should already be 2."""
from __future__ import annotations

from sqlalchemy import text


def test_attach_engine_at_runtime_runs_migrations(app):
    engine = app.config["FLEXLOG_DB_ENGINE"]
    with engine.begin() as c:
        version = c.execute(text("PRAGMA user_version")).scalar()
    assert version == 2
