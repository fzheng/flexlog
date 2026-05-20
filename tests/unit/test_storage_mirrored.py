"""MirroredStorage — sync replication wrapper.

Writes go to both primary and replica. If replica fails after primary
succeeded, primary is rolled back so the caller sees one consistent
failure (no orphan in primary)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_fake_backend():
    """In-memory fake backend with the StorageBackend interface.
    Tracks put/delete calls for assertions."""
    class _Fake:
        def __init__(self):
            self._data: dict[str, bytes] = {}
            self.put_calls = []
            self.delete_calls = []
            self.fail_next_put = False
            self.fail_next_delete = False

        def put(self, file_key, src_path):
            self.put_calls.append(file_key)
            if self.fail_next_put:
                self.fail_next_put = False
                raise RuntimeError("simulated put failure")
            self._data[file_key] = Path(src_path).read_bytes()

        def get_range(self, file_key, start, end):
            return self._data[file_key][start:end + 1]

        def get_size(self, file_key):
            return len(self._data[file_key])

        def exists(self, file_key):
            return file_key in self._data

        def delete(self, file_key):
            self.delete_calls.append(file_key)
            if self.fail_next_delete:
                self.fail_next_delete = False
                raise RuntimeError("simulated delete failure")
            self._data.pop(file_key, None)
    return _Fake()


def test_mirrored_put_writes_to_both(tmp_path):
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    storage = MirroredStorage(primary, replica)
    src = tmp_path / "x.bin"
    src.write_bytes(b"hello")
    storage.put("a/b/c.bin", src)
    assert primary.exists("a/b/c.bin")
    assert replica.exists("a/b/c.bin")
    assert primary.get_range("a/b/c.bin", 0, 4) == b"hello"
    assert replica.get_range("a/b/c.bin", 0, 4) == b"hello"


def test_mirrored_put_replica_failure_rolls_back_primary(tmp_path):
    """If replica put raises after primary put succeeded, primary
    is deleted so neither bucket has the orphan. Caller sees a single
    failure."""
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    replica.fail_next_put = True
    storage = MirroredStorage(primary, replica)
    src = tmp_path / "x.bin"
    src.write_bytes(b"hello")
    with pytest.raises(RuntimeError, match="simulated put failure"):
        storage.put("a/b/c.bin", src)
    # Neither bucket has the file
    assert not primary.exists("a/b/c.bin")
    assert not replica.exists("a/b/c.bin")
    # The rollback delete fired on primary
    assert "a/b/c.bin" in primary.delete_calls


def test_mirrored_put_primary_failure_doesnt_touch_replica(tmp_path):
    """If primary put fails, replica should never be touched."""
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    primary.fail_next_put = True
    storage = MirroredStorage(primary, replica)
    src = tmp_path / "x.bin"
    src.write_bytes(b"hello")
    with pytest.raises(RuntimeError, match="simulated put failure"):
        storage.put("a/b/c.bin", src)
    assert replica.put_calls == []
    assert not replica.exists("a/b/c.bin")


def test_mirrored_get_range_reads_only_from_primary(tmp_path):
    """Reads come from primary. Replica is silent on the read path
    (we don't want to double the GET cost)."""
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    src = tmp_path / "x.bin"
    src.write_bytes(b"hello world")
    storage = MirroredStorage(primary, replica)
    storage.put("a/b/c.bin", src)
    # Manually wipe replica to prove get_range doesn't touch it
    replica.delete("a/b/c.bin")
    assert storage.get_range("a/b/c.bin", 0, 4) == b"hello"


def test_mirrored_delete_calls_both(tmp_path):
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    storage = MirroredStorage(primary, replica)
    src = tmp_path / "x.bin"
    src.write_bytes(b"hello")
    storage.put("a/b/c.bin", src)
    storage.delete("a/b/c.bin")
    assert "a/b/c.bin" in primary.delete_calls
    assert "a/b/c.bin" in replica.delete_calls
    assert not primary.exists("a/b/c.bin")
    assert not replica.exists("a/b/c.bin")


def test_mirrored_delete_replica_failure_is_swallowed(tmp_path):
    """Replica delete failure is logged but doesn't raise — primary is
    already gone; the replica orphan is recoverable via a reconcile job."""
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    replica.fail_next_delete = True
    storage = MirroredStorage(primary, replica)
    src = tmp_path / "x.bin"
    src.write_bytes(b"hello")
    storage.put("a/b/c.bin", src)
    # Should NOT raise even though replica.delete raises
    storage.delete("a/b/c.bin")
    assert not primary.exists("a/b/c.bin")


def test_mirrored_get_size_from_primary(tmp_path):
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    storage = MirroredStorage(primary, replica)
    src = tmp_path / "x.bin"
    src.write_bytes(b"x" * 42)
    storage.put("a/b/c.bin", src)
    assert storage.get_size("a/b/c.bin") == 42


def test_mirrored_exists_from_primary(tmp_path):
    from flexlog.storage.mirrored import MirroredStorage
    primary = _make_fake_backend()
    replica = _make_fake_backend()
    storage = MirroredStorage(primary, replica)
    assert not storage.exists("missing.bin")
    src = tmp_path / "x.bin"
    src.write_bytes(b"x")
    storage.put("present.bin", src)
    assert storage.exists("present.bin")
