"""A `MigrationError` raised during a request renders the friendly
errors/migration_failed.html page instead of a bare 500."""
from __future__ import annotations


def test_migration_error_handler_renders_friendly_page(app):
    from flexlog.migrations.v1_to_v2 import MigrationError

    @app.route("/__test/_raise_migration_error")
    def _raise():
        raise MigrationError("simulated migration failure")

    client = app.test_client()
    import time
    with client.session_transaction() as sess:
        sess["authed"] = True
        sess["epoch"] = app.config["AUTH_EPOCH"]
        sess["last_seen"] = time.time()

    resp = client.get("/__test/_raise_migration_error")
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert "migration failed" in body.lower()
    assert "simulated migration failure" in body


def test_migrate_to_latest_wraps_underlying_exception():
    """The wrapper turns any underlying exception into MigrationError so
    the Flask error handler can catch it without enumerating every
    SQLAlchemy/SQLite/SQLCipher exception class."""
    from flexlog.migrations.v1_to_v2 import MigrationError, migrate_to_latest

    class FakeEngine:
        def begin(self):
            raise RuntimeError("disk full")

    import pytest
    with pytest.raises(MigrationError) as exc_info:
        migrate_to_latest(FakeEngine())  # type: ignore[arg-type]
    assert "disk full" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_migrate_to_latest_refuses_future_schema_version(tmp_path):
    """C1 fix: if a DB reports user_version > TARGET_VERSION (e.g. user
    downgraded flexlog), refuse to attach with a clear MigrationError
    rather than running the old ORM against a newer schema."""
    import pytest
    from sqlalchemy import create_engine, text
    from flexlog.migrations.v1_to_v2 import (
        MigrationError, TARGET_VERSION, migrate_to_latest,
    )

    # Plain SQLite (no encryption — we only need a DB that PRAGMA
    # user_version can be stamped on).
    db_path = tmp_path / "future.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION + 1}"))

    with pytest.raises(MigrationError) as exc_info:
        migrate_to_latest(engine)
    msg = str(exc_info.value)
    assert "newer than this build supports" in msg
    assert str(TARGET_VERSION + 1) in msg


def test_migrate_to_latest_accepts_equal_schema_version(tmp_path):
    """user_version == TARGET_VERSION must NOT trip the future-version
    guard — equal is the steady state for a freshly-migrated DB."""
    from sqlalchemy import create_engine, text
    from flexlog.migrations.v1_to_v2 import TARGET_VERSION, migrate_to_latest

    db_path = tmp_path / "current.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION}"))

    # No-op; should not raise.
    migrate_to_latest(engine)
