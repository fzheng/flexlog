"""DB backup worker — after_commit listener + background thread that
snapshots SQLCipher DB to S3 with last-30 rolling retention."""
from __future__ import annotations

import time
import threading
from pathlib import Path

import pytest


# A deterministic 32-byte master key for tests. Production master keys are
# random bytes from os.urandom; the value here just needs to be stable
# across the test so source + dest DBs use the same passphrase.
_TEST_MASTER_KEY = b"\xab" * 32


def _sqlcipher_key_hex(master_key: bytes) -> str:
    """Mirror the production derivation in landing_bp.py."""
    from flexlog.crypto import hkdf_subkey
    return hkdf_subkey(master_key, b"flexlog/sqlcipher/v1", 32).hex()


_TEST_SQLCIPHER_KEY_HEX = _sqlcipher_key_hex(_TEST_MASTER_KEY)


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


def _make_encrypted_db(path: Path, key_hex: str) -> None:
    """Create a real SQLCipher-encrypted DB at the given path with the
    given hex key — exactly the shape the production worker has to
    open."""
    from sqlcipher3 import dbapi2 as sqlcipher
    conn = sqlcipher.connect(str(path))
    try:
        conn.execute(f"PRAGMA key = \"x'{key_hex}'\"")
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    finally:
        conn.close()


class _FakeApp:
    """Minimal Flask-app stand-in for the worker. Only `.config.get(...)`
    is used."""
    def __init__(self, master_key=None):
        self.config = {"MASTER_KEY": master_key} if master_key else {}


def test_backup_now_uploads_with_iso_timestamp_key(tmp_path):
    """Direct invocation (no worker thread) — uploads a snapshot with
    a key matching backups/db-<ISO>.db pattern."""
    import re
    from flexlog.services.db_backup import backup_now

    storage = _make_fake_storage()
    db_file = tmp_path / "encounters.db"
    _make_encrypted_db(db_file, _TEST_SQLCIPHER_KEY_HEX)

    backup_now(storage, db_file, _TEST_SQLCIPHER_KEY_HEX)
    keys = storage.list_keys()
    assert len(keys) == 1
    assert re.match(
        r"^db/db-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z\.db$",
        keys[0],
    ), f"unexpected key shape: {keys[0]}"


def test_backup_now_produces_decryptable_snapshot(tmp_path):
    """Regression for the original deploy failure: backup_now must
    produce a file the SAME SQLCipher key can open. Plain sqlite3
    silently returned "file is not a database" on real SQLCipher
    inputs."""
    from sqlcipher3 import dbapi2 as sqlcipher
    from flexlog.services.db_backup import backup_now

    storage = _make_fake_storage()
    db_file = tmp_path / "encounters.db"
    _make_encrypted_db(db_file, _TEST_SQLCIPHER_KEY_HEX)
    backup_now(storage, db_file, _TEST_SQLCIPHER_KEY_HEX)

    # Materialize the uploaded bytes back to disk and try to open them
    # with the same key. If the backup is corrupt or written as
    # plaintext, this raises.
    key = storage.list_keys()[0]
    restored = tmp_path / "restored.db"
    restored.write_bytes(storage._objects[key])

    conn = sqlcipher.connect(str(restored))
    try:
        conn.execute(f"PRAGMA key = \"x'{_TEST_SQLCIPHER_KEY_HEX}'\"")
        rows = list(conn.execute("SELECT x FROM t"))
        assert rows == [(1,)]
    finally:
        conn.close()


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
    _make_encrypted_db(db_file, _TEST_SQLCIPHER_KEY_HEX)
    for _ in range(35):
        db_backup.backup_now(storage, db_file, _TEST_SQLCIPHER_KEY_HEX)
    keys = storage.list_keys(prefix="db/")
    assert len(keys) == 30
    assert len(storage.delete_calls) == 5


def test_find_latest_backup_returns_most_recent_key(tmp_path):
    """find_latest_backup returns the lexicographically-latest db/db-*.db key
    (which equals the chronologically-latest under our ISO naming)."""
    from flexlog.services.db_backup import find_latest_backup

    storage = _make_fake_storage()
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


def test_worker_skips_backup_when_master_key_missing(tmp_path):
    """When the user is logged out (no MASTER_KEY in app.config),
    the worker consumes the signal without backing up — the post-
    login next-commit will re-arm. This prevents repeated 'file is
    not a database' failures we observed before the SQLCipher fix."""
    from flexlog.services import db_backup
    from flexlog.services.db_backup import (
        _BACKUP_NEEDED, _spawn_worker_for_test,
    )

    storage = _make_fake_storage()
    db_file = tmp_path / "encounters.db"
    _make_encrypted_db(db_file, _TEST_SQLCIPHER_KEY_HEX)

    fake_app = _FakeApp(master_key=None)  # logged out
    stop = threading.Event()
    _spawn_worker_for_test(fake_app, storage, db_file, stop)

    _BACKUP_NEEDED.set()
    time.sleep(0.1)
    stop.set()
    _BACKUP_NEEDED.set()  # wake the worker so it can exit

    assert storage.put_calls == [], (
        "expected no backups (logged out); got "
        f"{storage.put_calls}"
    )
    _BACKUP_NEEDED.clear()
    db_backup._LAST_SUCCESS["at"] = None


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
    _make_encrypted_db(db_file, _TEST_SQLCIPHER_KEY_HEX)

    # Slow put() so the worker is still uploading while we fire the
    # remaining signals.
    original_put = storage.put

    def slow_put(key, src):
        time.sleep(0.2)
        original_put(key, src)

    storage.put = slow_put

    fake_app = _FakeApp(master_key=_TEST_MASTER_KEY)
    stop = threading.Event()
    _spawn_worker_for_test(fake_app, storage, db_file, stop)

    for _ in range(10):
        _BACKUP_NEEDED.set()
        time.sleep(0.005)

    time.sleep(0.6)
    stop.set()
    _BACKUP_NEEDED.set()  # wake the worker so it can exit

    assert 1 <= len(storage.put_calls) <= 2, (
        f"expected 1-2 put calls (coalescing), got "
        f"{len(storage.put_calls)}"
    )

    _BACKUP_NEEDED.clear()
    db_backup._LAST_SUCCESS["at"] = None
