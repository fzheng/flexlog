"""Storage backend package.

Public entry point: `get_storage()` returns the configured backend
based on FLEXLOG_STORAGE_BACKEND env var (`local` default, `s3` for
production)."""
from __future__ import annotations

import os

from flexlog.storage.backend import StorageBackend
from flexlog.storage.local import LocalStorage

__all__ = ["StorageBackend", "LocalStorage", "get_storage"]


def get_storage() -> StorageBackend:
    """Returns the storage backend per FLEXLOG_STORAGE_BACKEND env.
    Default `local` (LocalStorage). `s3` returns an S3Storage primary,
    optionally wrapped in MirroredStorage with a second S3Storage
    replica when BACKUP_BUCKET is set."""
    backend = os.environ.get("FLEXLOG_STORAGE_BACKEND", "local").lower()
    if backend == "local":
        from flexlog import paths
        return LocalStorage(base_dir=paths.uploads_dir())
    if backend == "s3":
        from flexlog.storage.s3 import S3Storage
        from flexlog.storage.mirrored import MirroredStorage

        primary = S3Storage(
            bucket=os.environ["BUCKET"],
            endpoint_url=os.environ.get("ENDPOINT"),
            region=os.environ.get("REGION", "auto"),
            access_key=os.environ["ACCESS_KEY_ID"],
            secret_key=os.environ["SECRET_ACCESS_KEY"],
            key_prefix="uploads/",
        )
        # If BACKUP_BUCKET is set, wrap in MirroredStorage for sync
        # replication. If not, return primary-only (useful for staging
        # environments with one bucket).
        backup_bucket = os.environ.get("BACKUP_BUCKET")
        if not backup_bucket:
            return primary
        replica = S3Storage(
            bucket=backup_bucket,
            endpoint_url=os.environ.get("BACKUP_ENDPOINT"),
            region=os.environ.get("BACKUP_REGION", "auto"),
            access_key=os.environ["BACKUP_ACCESS_KEY_ID"],
            secret_key=os.environ["BACKUP_SECRET_ACCESS_KEY"],
            key_prefix="media/",
        )
        return MirroredStorage(primary, replica)
    raise ValueError(
        f"FLEXLOG_STORAGE_BACKEND={backend!r} not supported; "
        f"use 'local' or 's3'"
    )
