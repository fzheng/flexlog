"""MirroredStorage — sync replication wrapper around two backends.

Writes (put, delete) go to both. Reads (get_range, get_size, exists)
come from primary only. If a put to replica fails after primary
succeeded, primary is rolled back so the caller sees one consistent
failure with no orphan.

This is the strong-consistency model the design picked over async
replication. Trade-off: ~200-400ms extra upload latency for guaranteed
2-bucket durability."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("flexlog.storage.mirrored")


class MirroredStorage:
    def __init__(self, primary, replica):
        self.primary = primary
        self.replica = replica

    def put(self, file_key: str, src_path: Path) -> None:
        self.primary.put(file_key, src_path)
        try:
            self.replica.put(file_key, src_path)
        except Exception:
            # Roll back primary so neither bucket has the orphan.
            # Caller sees one consistent failure (the original).
            try:
                self.primary.delete(file_key)
            except Exception as cleanup_exc:
                # Logged but not re-raised; the original replica failure
                # is what the caller needs to see.
                logger.warning(
                    "primary rollback after replica put failure also "
                    "failed for %s: %s", file_key, cleanup_exc,
                )
            raise

    def get_range(self, file_key: str, start: int, end: int) -> bytes:
        return self.primary.get_range(file_key, start, end)

    def get_size(self, file_key: str) -> int:
        return self.primary.get_size(file_key)

    def exists(self, file_key: str) -> bool:
        return self.primary.exists(file_key)

    def delete(self, file_key: str) -> None:
        # Delete from both, but a replica failure is non-fatal — primary
        # is gone, the replica orphan is recoverable via the reconcile
        # job described in docs/DEPLOYMENT.md.
        self.primary.delete(file_key)
        try:
            self.replica.delete(file_key)
        except Exception as e:
            logger.warning("replica delete failed for %s: %s", file_key, e)
