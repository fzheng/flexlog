"""Storage backend package.

Public entry point: `get_storage()` returns the configured backend
based on FLEXLOG_STORAGE_BACKEND env var (`local` default, `s3` for
production).

S3 mode env-var resolution: Railway's auto-injected names for a
linked Storage Bucket vary across plans/regions. We accept any of
the well-known aliases so a user doesn't have to rename things.

  Bucket name:    BUCKET   | BUCKET_NAME | S3_BUCKET | AWS_S3_BUCKET_NAME
  Endpoint URL:   ENDPOINT | S3_ENDPOINT | ENDPOINT_URL | AWS_ENDPOINT_URL
  Region:         REGION   | AWS_DEFAULT_REGION | AWS_REGION
  Access key id:  ACCESS_KEY_ID | AWS_ACCESS_KEY_ID
  Secret key:     SECRET_ACCESS_KEY | AWS_SECRET_ACCESS_KEY

The BACKUP_ prefix variants are the same names with BACKUP_ in front
(BACKUP_BUCKET, BACKUP_BUCKET_NAME, BACKUP_ENDPOINT, ...).

If a required variable is missing under all accepted aliases, we
raise a clear RuntimeError listing what was searched + which
bucket-shaped env vars ARE set, so the deployer can read the log
and fix the config in one pass."""
from __future__ import annotations

import os
from typing import Iterable

from flexlog.storage.backend import StorageBackend
from flexlog.storage.local import LocalStorage

__all__ = ["StorageBackend", "LocalStorage", "get_storage"]


_BUCKET_ALIASES = ("BUCKET", "BUCKET_NAME", "S3_BUCKET", "AWS_S3_BUCKET_NAME")
_ENDPOINT_ALIASES = ("ENDPOINT", "S3_ENDPOINT", "ENDPOINT_URL", "AWS_ENDPOINT_URL")
_REGION_ALIASES = ("REGION", "AWS_DEFAULT_REGION", "AWS_REGION")
_ACCESS_KEY_ALIASES = ("ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID")
_SECRET_KEY_ALIASES = ("SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY")


def _first_env(names: Iterable[str], prefix: str = "") -> str | None:
    """Return the first present env var value among names (with optional
    BACKUP_ prefix)."""
    for n in names:
        v = os.environ.get(f"{prefix}{n}")
        if v:
            return v
    return None


def _require_env(names: Iterable[str], prefix: str, label: str) -> str:
    """Like _first_env but raises a clear error listing what was tried
    + what bucket-shaped vars ARE present."""
    val = _first_env(names, prefix)
    if val:
        return val
    tried = [f"{prefix}{n}" for n in names]
    present = sorted(
        k for k in os.environ
        if any(tok in k for tok in ("BUCKET", "ENDPOINT", "REGION",
                                    "ACCESS_KEY", "SECRET"))
    )
    raise RuntimeError(
        f"FLEXLOG_STORAGE_BACKEND=s3 needs {label} but none of "
        f"{tried} are set. Bucket-shaped env vars currently present: "
        f"{present or '(none)'}. Link the bucket in the Railway "
        f"dashboard or rename the variable to one of: {tried}."
    )


def _build_s3_storage(prefix: str, key_prefix: str):
    """Build an S3Storage from env vars under the given prefix
    (empty for primary, 'BACKUP_' for replica)."""
    from flexlog.storage.s3 import S3Storage
    return S3Storage(
        bucket=_require_env(_BUCKET_ALIASES, prefix, f"{prefix}BUCKET"),
        endpoint_url=_first_env(_ENDPOINT_ALIASES, prefix),
        region=_first_env(_REGION_ALIASES, prefix) or "auto",
        access_key=_require_env(_ACCESS_KEY_ALIASES, prefix,
                                f"{prefix}ACCESS_KEY_ID"),
        secret_key=_require_env(_SECRET_KEY_ALIASES, prefix,
                                f"{prefix}SECRET_ACCESS_KEY"),
        key_prefix=key_prefix,
    )


def get_storage() -> StorageBackend:
    """Returns the storage backend per FLEXLOG_STORAGE_BACKEND env.
    Default `local` (LocalStorage). `s3` returns an S3Storage primary,
    optionally wrapped in MirroredStorage with a second S3Storage
    replica when a backup bucket is configured."""
    backend = os.environ.get("FLEXLOG_STORAGE_BACKEND", "local").lower()
    if backend == "local":
        from flexlog import paths
        return LocalStorage(base_dir=paths.uploads_dir())
    if backend == "s3":
        primary = _build_s3_storage(prefix="", key_prefix="uploads/")
        # Replica is opt-in via any of the backup-bucket aliases.
        if not _first_env(_BUCKET_ALIASES, prefix="BACKUP_"):
            return primary
        from flexlog.storage.mirrored import MirroredStorage
        replica = _build_s3_storage(prefix="BACKUP_", key_prefix="media/")
        return MirroredStorage(primary, replica)
    raise ValueError(
        f"FLEXLOG_STORAGE_BACKEND={backend!r} not supported; "
        f"use 'local' or 's3'"
    )
