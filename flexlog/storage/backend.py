"""Abstract StorageBackend protocol.

Every byte that flows through this interface is already AES-GCM-
encrypted by flexlog/crypto.py. The backend's job is just to hold
opaque bytes and serve them back by content-addressed key, with
HTTP-Range-style partial reads for streaming decrypt.

Implementations: LocalStorage (filesystem) and S3Storage (boto3).
MirroredStorage wraps two backends for redundancy."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Implementations must be thread-safe (the DB-backup worker +
    request threads share). file_key is the same sharded SHA-based
    path the existing code uses: `<aa>/<bb>/<sha>.<ext>`."""

    def put(self, file_key: str, src_path: Path) -> None:
        """Upload the bytes of src_path under file_key. Atomic from
        the caller's perspective: either the bytes are fully there
        or the key doesn't exist."""

    def get_range(self, file_key: str, start: int, end: int) -> bytes:
        """Return bytes [start, end] inclusive on both ends. Caller
        guarantees end < get_size(file_key)."""

    def get_size(self, file_key: str) -> int:
        """Total bytes stored under file_key. Used by media_bp to
        validate Range header bounds."""

    def exists(self, file_key: str) -> bool:
        """True if file_key is present and readable."""

    def delete(self, file_key: str) -> None:
        """Best-effort delete. Missing key is not an error."""
