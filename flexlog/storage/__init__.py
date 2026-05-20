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
    Default `local` (LocalStorage). `s3` returns S3Storage (added in
    Phase B); `mirrored` returns MirroredStorage of primary + backup
    S3Storage instances (added in Phase B)."""
    backend = os.environ.get("FLEXLOG_STORAGE_BACKEND", "local").lower()
    if backend == "local":
        from flexlog import paths
        return LocalStorage(base_dir=paths.uploads_dir())
    # s3 / mirrored handled in Phase B
    raise ValueError(
        f"FLEXLOG_STORAGE_BACKEND={backend!r} not supported yet "
        f"(only 'local' is currently supported)"
    )
