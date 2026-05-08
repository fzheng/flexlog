"""Sandboxed filesystem API for flexlog.

All disk I/O elsewhere in the app must go through this module so we have a
single place that:
  - validates the FLEXLOG_DATA_DIR environment variable at startup
  - resolves child paths under that directory
  - rejects file keys that try to escape the uploads/ root

The full file-key API (resolve_file_key, file_key_for) is added in Task 3.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_DIR = "FLEXLOG_DATA_DIR"


class DataDirError(RuntimeError):
    """Raised when FLEXLOG_DATA_DIR is missing or unusable."""


def data_dir() -> Path:
    """Return the validated FLEXLOG_DATA_DIR as a Path.

    Raises DataDirError if the variable is unset, empty, relative, missing,
    not a directory, or not writable.
    """
    raw = os.environ.get(ENV_DATA_DIR, "").strip()
    if not raw:
        raise DataDirError(
            f"{ENV_DATA_DIR} is not set. Set it to an absolute path to a writable directory."
        )
    p = Path(raw)
    if not p.is_absolute():
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} must be an absolute path."
        )
    if not p.exists():
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} does not exist. Create the directory before running flexlog."
        )
    if not p.is_dir():
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} is not a directory."
        )
    if not os.access(p, os.W_OK):
        raise DataDirError(
            f"{ENV_DATA_DIR}={raw!r} is not writable by the current user."
        )
    return p


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "data" / "encounters.db"


def uploads_dir() -> Path:
    return data_dir() / "uploads"


def tmp_uploads_dir() -> Path:
    return uploads_dir() / ".tmp"


def ensure_layout() -> None:
    """Create the standard child directories if missing. Idempotent."""
    (data_dir() / "data").mkdir(parents=True, exist_ok=True)
    uploads_dir().mkdir(parents=True, exist_ok=True)
    tmp_uploads_dir().mkdir(parents=True, exist_ok=True)
