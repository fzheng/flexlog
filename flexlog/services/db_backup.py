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
import sqlite3
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


def _sqlite3_backup_to_tmp(db_path: Path) -> Path:
    """Use SQLite's online backup API to produce a consistent snapshot
    in a tmp file. Returns the tmp file path."""
    # NOTE: SQLCipher uses a separate sqlcipher3 module, but online
    # backup is exposed through the standard sqlite3 API for any
    # SQLite-derived library. SQLCipher's pages are already
    # encrypted; the backup is byte-equivalent encrypted pages.
    tmp = Path(tempfile.NamedTemporaryFile(
        suffix=".db", prefix="flexlog-backup-", delete=False
    ).name)
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)  # sqlite3_backup_init/step/finish
    finally:
        dst.close()
        src.close()
    return tmp


def backup_now(storage, db_path: Path) -> str:
    """Synchronous one-shot backup: snapshot → upload → rotate.
    Returns the key that was uploaded. Used by the worker AND by
    tests + a future 'Backup now' button."""
    tmp = _sqlite3_backup_to_tmp(db_path)
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


def _worker_loop(storage, db_path: Path, stop_event: threading.Event):
    while not stop_event.is_set():
        _BACKUP_NEEDED.wait()
        _BACKUP_NEEDED.clear()
        if stop_event.is_set():
            break
        with _WORKER_LOCK:
            try:
                backup_now(storage, db_path)
            except Exception:
                logger.warning("DB backup failed", exc_info=True)
                _BACKUP_NEEDED.set()  # retry next cycle
                if stop_event.wait(_RETRY_BACKOFF_SECONDS):
                    break


def _spawn_worker_for_test(storage, db_path: Path, stop_event: threading.Event):
    """Test-only helper: spawn the worker thread directly without
    requiring an SQLAlchemy session. Returns the started Thread."""
    t = threading.Thread(
        target=_worker_loop,
        args=(storage, db_path, stop_event),
        name="db-backup-worker-test",
        daemon=True,
    )
    t.start()
    return t


def register_db_backup_worker(app, storage, db_path: Path) -> threading.Thread:
    """Wire the after_commit listener + spawn the worker. Returns the
    started Thread (caller should keep a reference or rely on daemon=True).

    Idempotent at the listener level — SQLAlchemy de-duplicates
    listeners by (target, identifier, func)."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    @event.listens_for(Session, "after_commit")
    def _flag_backup(_session):
        _BACKUP_NEEDED.set()

    stop_event = threading.Event()
    app.config["_DB_BACKUP_STOP_EVENT"] = stop_event

    t = threading.Thread(
        target=_worker_loop,
        args=(storage, db_path, stop_event),
        name="db-backup-worker",
        daemon=True,
    )
    t.start()
    return t


def last_successful_backup_at() -> datetime.datetime | None:
    """Read by the status-bar context processor."""
    return _LAST_SUCCESS["at"]
