"""DB backup worker.

On every successful db.commit(), the after_commit listener sets a
threading.Event. A daemon thread waits on the event, snapshots the
SQLCipher DB via sqlite3_backup (consistent online backup), uploads
to S3 under db/db-<ISO>.db, applies last-30 rolling retention, and
sleeps until the next signal.

Coalescing: multiple commits during one upload-in-flight collapse
into the next single upload."""
from __future__ import annotations

import datetime
import logging
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger("flexlog.db_backup")

# Module-level signaling. The worker thread waits on this; commits set it.
_BACKUP_NEEDED = threading.Event()
_WORKER_LOCK = threading.Lock()
_LAST_SUCCESS: dict[str, datetime.datetime | None] = {"at": None}

_DB_BACKUP_PREFIX = "db/"
_KEEP_LAST_N = 30
_RETRY_BACKOFF_SECONDS = 30


def _iso_now() -> str:
    """UTC timestamp like 2026-05-19T14-23-45Z. Hyphens (not colons)
    so the key is filesystem-safe across all S3 implementations."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0, tzinfo=None
    )
    return now.strftime("%Y-%m-%dT%H-%M-%SZ")


def _backup_key() -> str:
    return f"{_DB_BACKUP_PREFIX}db-{_iso_now()}.db"


def _sqlcipher_backup_to_tmp(db_path: Path, sqlcipher_key_hex: str) -> Path:
    """Use SQLCipher's online backup API to produce a consistent
    snapshot. Both source and destination are SQLCipher-encrypted
    with the same key — the backup file on disk is encrypted bytes
    ready to upload to S3.

    Earlier versions of this function used the standard library
    sqlite3 module, but it cannot open a SQLCipher-encrypted DB
    (the file header itself is encrypted), so backups silently
    failed in production with "file is not a database"."""
    from sqlcipher3 import dbapi2 as sqlcipher

    tmp = Path(tempfile.NamedTemporaryFile(
        suffix=".db", prefix="flexlog-backup-", delete=False
    ).name)
    src = sqlcipher.connect(str(db_path))
    dst = sqlcipher.connect(str(tmp))
    try:
        # PRAGMA key must run before any other statement on each
        # connection. Same key for source + destination so the
        # backup file is encrypted under the same passphrase as
        # the live DB.
        src.execute(f"PRAGMA key = \"x'{sqlcipher_key_hex}'\"")
        dst.execute(f"PRAGMA key = \"x'{sqlcipher_key_hex}'\"")
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return tmp


def backup_now(storage, db_path: Path, sqlcipher_key_hex: str) -> str:
    """Synchronous one-shot backup: snapshot → upload → rotate.
    Returns the key that was uploaded. Used by the worker AND by
    tests + a future 'Backup now' button."""
    tmp = _sqlcipher_backup_to_tmp(db_path, sqlcipher_key_hex)
    try:
        key = _backup_key()
        storage.put(key, tmp)
        _rotate(storage)
        _LAST_SUCCESS["at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).replace(tzinfo=None)
        return key
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _rotate(storage) -> None:
    """Delete any backup beyond the _KEEP_LAST_N most recent."""
    # Duck-typed: list_keys is added to S3Storage in this task;
    # LocalStorage and MirroredStorage don't expose it (rotation
    # is a backup-bucket concern only).
    if not hasattr(storage, "list_keys"):
        return
    keys = storage.list_keys(prefix=_DB_BACKUP_PREFIX)
    # Sorted lexicographically; with ISO-8601 timestamps that equals
    # chronological order.
    excess = keys[:-_KEEP_LAST_N] if len(keys) > _KEEP_LAST_N else []
    for k in excess:
        try:
            storage.delete(k)
        except Exception as e:
            logger.warning("failed to rotate backup %s: %s", k, e)


def find_latest_backup(storage) -> str | None:
    """Return the lexicographically-newest db/db-*.db key, or None."""
    if not hasattr(storage, "list_keys"):
        return None
    keys = storage.list_keys(prefix=_DB_BACKUP_PREFIX)
    return keys[-1] if keys else None


def _worker_loop(
    app, storage, db_path: Path, stop_event: threading.Event,
):
    """Wait for a commit signal, fetch the current master key from
    the app config (only present after login), derive the SQLCipher
    passphrase, snapshot + upload.

    If the user is logged out (no MASTER_KEY in app.config), the
    signal is consumed silently — there's nothing to back up that
    we can read anyway. Next post-login commit re-arms the signal."""
    from flexlog.crypto import hkdf_subkey

    while not stop_event.is_set():
        _BACKUP_NEEDED.wait()
        _BACKUP_NEEDED.clear()
        if stop_event.is_set():
            break
        with _WORKER_LOCK:
            try:
                master_key = app.config.get("MASTER_KEY") if app else None
                if not master_key:
                    # Logged out → nothing to back up; wait for next commit.
                    continue
                sqlcipher_key_hex = hkdf_subkey(
                    master_key, b"flexlog/sqlcipher/v1", 32,
                ).hex()
                backup_now(storage, db_path, sqlcipher_key_hex)
            except Exception:
                logger.warning("DB backup failed", exc_info=True)
                _BACKUP_NEEDED.set()  # retry next cycle
                if stop_event.wait(_RETRY_BACKOFF_SECONDS):
                    break


def _spawn_worker_for_test(
    app, storage, db_path: Path, stop_event: threading.Event,
):
    """Test-only helper: spawn the worker thread directly without
    requiring an SQLAlchemy session. `app` is a Flask-app-like object
    with a `config` dict containing MASTER_KEY (the test can pass a
    real Flask app, a Mock, or any object exposing .config.get)."""
    t = threading.Thread(
        target=_worker_loop,
        args=(app, storage, db_path, stop_event),
        name="db-backup-worker-test",
        daemon=True,
    )
    t.start()
    return t


def register_db_backup_worker(app, storage, db_path: Path) -> threading.Thread:
    """Wire the after_commit listener + spawn the worker. Returns the
    started Thread (caller should keep a reference or rely on daemon=True).

    Idempotent at the listener level — SQLAlchemy de-duplicates
    listeners by (target, identifier, func). The worker captures
    `app` so it can read app.config["MASTER_KEY"] at backup time
    (the key is only present post-login)."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    @event.listens_for(Session, "after_commit")
    def _flag_backup(_session):
        _BACKUP_NEEDED.set()

    stop_event = threading.Event()
    app.config["_DB_BACKUP_STOP_EVENT"] = stop_event

    t = threading.Thread(
        target=_worker_loop,
        args=(app, storage, db_path, stop_event),
        name="db-backup-worker",
        daemon=True,
    )
    t.start()
    return t


def last_successful_backup_at() -> datetime.datetime | None:
    """Read by the status-bar context processor."""
    return _LAST_SUCCESS["at"]


def restore_latest_if_missing(storage, db_path: Path) -> bool:
    """If db_path doesn't exist AND a backup exists in storage,
    download the latest backup to db_path. Returns True iff a
    restore happened.

    Used at app boot (`create_app`) when running with
    FLEXLOG_STORAGE_BACKEND=s3 — handles the cold-start case
    where Railway gave us a fresh Volume."""
    if db_path.exists():
        return False
    latest_key = find_latest_backup(storage)
    if latest_key is None:
        return False
    size = storage.get_size(latest_key)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db_path.open("wb") as f:
        CHUNK = 4 * 1024 * 1024  # 4 MiB
        offset = 0
        while offset < size:
            end = min(offset + CHUNK - 1, size - 1)
            f.write(storage.get_range(latest_key, offset, end))
            offset = end + 1
    logger.info("Restored DB from %s to %s", latest_key, db_path)
    return True
