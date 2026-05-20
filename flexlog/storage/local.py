"""LocalStorage — filesystem-backed StorageBackend.

Wraps the existing paths.resolve_file_key() logic without changing
on-disk format. Used for `make run` (local dev) and every test that
doesn't explicitly target S3."""
from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path


class LocalStorage:
    """Filesystem-backed StorageBackend. `base_dir` is the root that
    file_keys are resolved against (typically `$FLEXLOG_DATA_DIR/uploads`)."""

    def __init__(self, base_dir: Path):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, file_key: str) -> Path:
        return self._base / file_key

    def put(self, file_key: str, src_path: Path) -> None:
        dst = self._path(file_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Write to a randomized tmp path in the same shard dir, then
        # os.replace into place — atomic on POSIX so a concurrent
        # get_range never sees partial bytes (would fail GCM tag check).
        tmp = dst.with_suffix(dst.suffix + f".{secrets.token_hex(8)}.tmp")
        try:
            shutil.copyfile(src_path, tmp)
            os.replace(tmp, dst)
        except Exception:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise

    def get_range(self, file_key: str, start: int, end: int) -> bytes:
        with self._path(file_key).open("rb") as f:
            f.seek(start)
            return f.read(end - start + 1)

    def get_size(self, file_key: str) -> int:
        return self._path(file_key).stat().st_size

    def exists(self, file_key: str) -> bool:
        return self._path(file_key).is_file()

    def delete(self, file_key: str) -> None:
        try:
            self._path(file_key).unlink()
        except FileNotFoundError:
            pass
