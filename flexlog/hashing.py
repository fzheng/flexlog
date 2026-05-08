"""Streaming SHA-256 helper for content-addressed storage."""

from __future__ import annotations

import hashlib
from typing import BinaryIO

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def sha256_hex_stream(reader: BinaryIO, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Compute SHA-256 over `reader` in chunks, returning the hex digest.

    The reader must be binary; calling this on a text stream raises TypeError.
    Reads to EOF and does not seek back. Caller is responsible for stream
    positioning before/after.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    h = hashlib.sha256()
    while True:
        chunk = reader.read(chunk_size)
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError(
                f"sha256_hex_stream requires a binary reader; got chunk of type {type(chunk).__name__}"
            )
        h.update(chunk)
    return h.hexdigest()
