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


# --- File-key API ---

# MIME → extension allowlist. Must match spec §4.4.
_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}

_HEX = set("0123456789abcdef")


class FileKeyError(ValueError):
    """Raised when a file key is malformed or escapes the uploads sandbox."""


def file_key_for(sha256_hex: str, mime_type: str) -> str:
    """Produce the canonical file key for a uniquely-identified upload.

    Layout: "<aa>/<bb>/<full-sha>.<ext>" where aa and bb are the first two
    hex byte-pairs of the SHA-256 digest. The extension is chosen from a
    fixed allowlist of MIME types.
    """
    if (
        not isinstance(sha256_hex, str)
        or len(sha256_hex) != 64
        or any(c not in _HEX for c in sha256_hex)
    ):
        raise FileKeyError(
            f"invalid sha256 digest: must be 64 lowercase hex chars, got {sha256_hex!r}"
        )
    ext = _MIME_TO_EXT.get(mime_type)
    if ext is None:
        raise FileKeyError(f"unsupported mime type: {mime_type!r}")
    return f"{sha256_hex[0:2]}/{sha256_hex[2:4]}/{sha256_hex}.{ext}"


def resolve_file_key(file_key: str) -> Path:
    """Resolve a file key to an absolute path under uploads/ — sandboxed.

    Raises FileKeyError if the key is empty, contains a NUL byte, is
    absolute, resolves to the uploads root itself, or resolves outside the
    uploads root (including via symlinks).
    """
    if not isinstance(file_key, str) or file_key == "":
        raise FileKeyError("file key is empty")
    if "\x00" in file_key:
        raise FileKeyError("file key contains NUL byte")
    if file_key.startswith("/") or (len(file_key) > 1 and file_key[1] == ":"):
        # Block POSIX-absolute and Windows-style absolute keys.
        raise FileKeyError(f"file key must be relative, got absolute: {file_key!r}")
    base = uploads_dir().resolve()
    try:
        candidate = (base / file_key).resolve()
    except (OSError, ValueError) as exc:
        raise FileKeyError(f"file key {file_key!r} could not be resolved") from exc
    try:
        rel = candidate.relative_to(base)
    except ValueError as exc:
        raise FileKeyError(
            f"file key {file_key!r} escapes uploads sandbox"
        ) from exc
    if rel == Path("."):
        # Resolved path equals uploads root — not a file inside it.
        raise FileKeyError(f"file key {file_key!r} resolves to uploads root")
    return candidate
