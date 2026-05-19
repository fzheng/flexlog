"""Unit tests for the status-bar service.

compute_status(db, data_dir) returns a StatusSnapshot with:
  - storage_bytes: sum of every regular file's size under data_dir
  - last_session_at: max(session.updated_at) as a UTC datetime, or None
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_humanize_bytes_zero():
    from flexlog.services.status import humanize_bytes
    assert humanize_bytes(0) == "0 B"


def test_humanize_bytes_under_1k():
    from flexlog.services.status import humanize_bytes
    assert humanize_bytes(1) == "1 B"
    assert humanize_bytes(1023) == "1023 B"


def test_humanize_bytes_kib():
    from flexlog.services.status import humanize_bytes
    assert humanize_bytes(1024) == "1.0 KB"
    assert humanize_bytes(1024 * 1024 - 1) == "1024.0 KB"


def test_humanize_bytes_mib():
    from flexlog.services.status import humanize_bytes
    assert humanize_bytes(1024 * 1024) == "1.0 MB"
    assert humanize_bytes(int(2.4 * 1024 * 1024 * 1024)) == "2.4 GB"


def test_humanize_bytes_tib():
    from flexlog.services.status import humanize_bytes
    assert humanize_bytes(1024 ** 4) == "1.0 TB"


def test_compute_status_empty_dir_empty_db(tmp_path, db_session):
    """No sessions, no files -> 0 bytes + None last-session."""
    from flexlog.services.status import compute_status, StatusSnapshot
    # The db_session fixture bootstraps an encrypted DB inside pytest's
    # tmp_path. Use a sibling scratch dir so the walk sees an empty tree.
    scratch = tmp_path.parent / (tmp_path.name + "_status_empty")
    scratch.mkdir()
    snap = compute_status(db_session, scratch)
    assert isinstance(snap, StatusSnapshot)
    assert snap.storage_bytes == 0
    assert snap.last_session_at is None


def test_compute_status_counts_all_files_recursively(tmp_path, db_session):
    """rglob over the data dir picks up nested files; the total matches
    sum-of-sizes regardless of depth."""
    from flexlog.services.status import compute_status
    scratch = tmp_path.parent / (tmp_path.name + "_status_walk")
    scratch.mkdir()
    (scratch / "config.json").write_bytes(b"x" * 100)
    (scratch / "data").mkdir()
    (scratch / "data" / "encounters.db").write_bytes(b"y" * 5000)
    (scratch / "uploads" / "ab" / "cd").mkdir(parents=True)
    (scratch / "uploads" / "ab" / "cd" / "abcdef.jpg").write_bytes(b"z" * 12345)
    snap = compute_status(db_session, scratch)
    assert snap.storage_bytes == 100 + 5000 + 12345


def test_compute_status_skips_unreadable_files(tmp_path, db_session, monkeypatch):
    """A PermissionError on a single file shouldn't crash the walk;
    that file is skipped and the total is understated by its size."""
    from flexlog.services.status import compute_status
    scratch = tmp_path.parent / (tmp_path.name + "_status_perm")
    scratch.mkdir()
    good = scratch / "good.bin"
    good.write_bytes(b"x" * 100)
    bad = scratch / "bad.bin"
    bad.write_bytes(b"y" * 200)

    original_stat = type(bad).stat
    def selective_stat(self, *a, **kw):
        if self.name == "bad.bin":
            raise PermissionError("simulated")
        return original_stat(self, *a, **kw)
    monkeypatch.setattr(type(bad), "stat", selective_stat)

    snap = compute_status(db_session, scratch)
    assert snap.storage_bytes == 100  # bad.bin skipped


def test_compute_status_returns_max_updated_at(person, db_session):
    """Insert two sessions; the snapshot's last_session_at equals the
    later one's updated_at (as a UTC-aware datetime)."""
    from flexlog.services.sessions import create_session
    from flexlog.services.status import compute_status

    s1 = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 3}, notes=None, link_urls=[], link_thumb_keys=[],
    )
    db_session.commit()
    s2 = create_session(
        db_session, person_id=person.id, session_date="2026-05-18",
        ratings={"energy": 4}, notes=None, link_urls=[], link_thumb_keys=[],
    )
    db_session.commit()

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        snap = compute_status(db_session, Path(td))
    assert snap.last_session_at is not None
    assert snap.last_session_at.tzinfo is not None  # tz-aware
    # The later session's updated_at must equal the snapshot value.
    assert s2.updated_at == snap.last_session_at.isoformat(timespec="microseconds")


def test_session_updated_at_bumps_on_update_session(person, db_session):
    """Regression guard for the spec's stated risk: SQLAlchemy's
    `onupdate` only fires on a SET of a column on the parent row.
    `update_session` always SETs session_date/ratings_json/notes, so
    onupdate should fire and `updated_at` should change. If a future
    refactor removes those SETs and only mutates the links collection,
    this test will catch the regression — at which point add an
    explicit `session_row.updated_at = _utcnow_iso()` in update_session.
    """
    import time
    from flexlog.services.sessions import create_session, update_session

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 3}, notes=None, link_urls=[], link_thumb_keys=[],
    )
    db_session.commit()
    initial = s.updated_at

    time.sleep(0.01)  # ensure clock advances past microsecond precision

    update_session(
        db_session, session_id=s.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=[], link_thumb_keys=[],
    )
    db_session.commit()
    db_session.refresh(s)
    assert s.updated_at > initial, (
        f"updated_at didn't advance: was {initial!r}, still {s.updated_at!r}. "
        "If this fires, add an explicit timestamp set in update_session."
    )


def test_max_session_updated_at_logs_warning_on_malformed_iso(person, db_session, caplog):
    """If a corrupted updated_at value lands in the DB (e.g. external
    edit), compute_status logs a warning and returns None instead of
    crashing the status bar."""
    import logging
    from sqlalchemy import text
    from flexlog.services.sessions import create_session
    from flexlog.services.status import compute_status

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-18",
        ratings={"energy": 4}, notes=None, link_urls=[], link_thumb_keys=[],
    )
    db_session.commit()
    # Poison the row with a non-ISO timestamp.
    db_session.execute(
        text("UPDATE session SET updated_at = :bad WHERE id = :i"),
        {"bad": "not-an-iso-8601-string", "i": s.id},
    )
    db_session.commit()

    import tempfile
    from pathlib import Path
    with caplog.at_level(logging.WARNING, logger="flexlog.status"):
        with tempfile.TemporaryDirectory() as td:
            snap = compute_status(db_session, Path(td))

    assert snap.last_session_at is None
    assert any(
        "malformed" in r.message.lower() and "updated_at" in r.message.lower()
        for r in caplog.records
    ), f"expected warning logged; got: {[r.message for r in caplog.records]}"
