"""DB backup worker — after_commit listener + background thread that
snapshots SQLCipher DB to S3 with last-30 rolling retention."""
from __future__ import annotations

import time
import threading
from pathlib import Path

import pytest


def _make_fake_storage():
    """Fake storage with put/delete and a key list for assertions."""
    class _Fake:
        def __init__(self):
            self._objects = {}  # key -> bytes
            self.put_calls = []
            self.delete_calls = []

        def put(self, file_key, src_path):
            self.put_calls.append(file_key)
            self._objects[file_key] = Path(src_path).read_bytes()

        def delete(self, file_key):
            self.delete_calls.append(file_key)
            self._objects.pop(file_key, None)

        def list_keys(self, prefix=""):
            return sorted(k for k in self._objects if k.startswith(prefix))

        def exists(self, file_key):
            return file_key in self._objects

        def get_size(self, file_key):
            return len(self._objects[file_key])

        def get_range(self, file_key, start, end):
            return self._objects[file_key][start:end + 1]
    return _Fake()


def _make_real_sqlite_db(path: Path) -> None:
    """Create a real (tiny) SQLite DB at the given path so sqlite3
    online backup can read it."""
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    finally:
        conn.close()


def test_backup_now_uploads_with_iso_timestamp_key(tmp_path):
    """Direct invocation (no worker thread) — uploads a snapshot with
    a key matching backups/db-<ISO>.db pattern."""
    import re
    from flexlog.services.db_backup import backup_now

    storage = _make_fake_storage()
    db_file = tmp_path / "encounters.db"
    _make_real_sqlite_db(db_file)

    backup_now(storage, db_file)
    keys = storage.list_keys()
    assert len(keys) == 1
    assert re.match(
        r"^db/db-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.db$",
        keys[0],
    ), f"unexpected key shape: {keys[0]}"


def test_backup_now_rotates_keeping_last_30(tmp_path, monkeypatch):
    """After 35 backup_now calls, only the 30 newest remain."""
    from flexlog.services import db_backup

    counter = {"n": 0}

    def fake_key():
        counter["n"] += 1
        return f"db/db-2026-01-01T00-00-{counter['n']:02d}Z.db"

    monkeypatch.setattr(db_backup, "_backup_key", fake_key)

    storage = _make_fake_storage()
    db_file = tmp_path / "encounters.db"
    _make_real_sqlite_db(db_file)
    for _ in range(35):
        db_backup.backup_now(storage, db_file)
    keys = storage.list_keys(prefix="db/")
    assert len(keys) == 30
    assert len(storage.delete_calls) == 5


def test_find_latest_backup_returns_most_recent_key(tmp_path):
    """find_latest_backup returns the lexicographically-latest db/db-*.db key
    (which equals the chronologically-latest under our ISO naming)."""
    from flexlog.services.db_backup import find_latest_backup

    storage = _make_fake_storage()
    # Plant backups out of order
    for k in [
        "db/db-2026-05-19T10-00-00Z.db",
        "db/db-2026-05-19T12-00-00Z.db",
        "db/db-2026-05-19T11-00-00Z.db",
    ]:
        storage._objects[k] = b"x"
    latest = find_latest_backup(storage)
    assert latest == "db/db-2026-05-19T12-00-00Z.db"


def test_find_latest_backup_returns_none_when_empty(tmp_path):
    from flexlog.services.db_backup import find_latest_backup
    storage = _make_fake_storage()
    assert find_latest_backup(storage) is None


def test_worker_coalesces_multiple_signals(tmp_path):
    """If the after_commit fires 10 times while one upload is in flight,
    we get ONE additional upload (not 10) once the in-flight completes.

    To exercise the in-flight-coalescing window, we slow put() so the
    first backup is still uploading while we fire the rest of the
    signals."""
    from flexlog.services import db_backup
    from flexlog.services.db_backup import (
        _BACKUP_NEEDED, _spawn_worker_for_test,
    )

    storage = _make_fake_storage()
    db_file = tmp_path / "encounters.db"
    _make_real_sqlite_db(db_file)

    # Make put() slow so the worker is still uploading while we
    # fire the remaining signals.
    original_put = storage.put

    def slow_put(key, src):
        time.sleep(0.2)
        original_put(key, src)

    storage.put = slow_put

    # Spawn the worker
    stop = threading.Event()
    _spawn_worker_for_test(storage, db_file, stop)

    # Signal many times in quick succession (all 10 land while the
    # first slow put is in flight)
    for _ in range(10):
        _BACKUP_NEEDED.set()
        time.sleep(0.005)

    # Wait long enough for the in-flight upload + one coalesced
    # follow-up to complete.
    time.sleep(0.6)
    stop.set()
    _BACKUP_NEEDED.set()  # wake the worker so it can exit

    # Should have at most 2 uploads: one for the first signal, one
    # coalescing all the rest. (Could be 1 if all signals landed
    # before the worker's first wake.)
    assert 1 <= len(storage.put_calls) <= 2, (
        f"expected 1-2 put calls (coalescing), got "
        f"{len(storage.put_calls)}"
    )

    # Cleanup module-level state so later tests start clean
    _BACKUP_NEEDED.clear()
    db_backup._LAST_SUCCESS["at"] = None
