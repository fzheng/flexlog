"""LocalStorage backend — wraps the existing paths.resolve_file_key()
logic in the StorageBackend interface. Behavior must be byte-identical
to direct filesystem use."""
from __future__ import annotations

import pytest


def test_local_storage_round_trip(tmp_path):
    """put → get_range across the whole file → identical bytes."""
    from flexlog.storage.local import LocalStorage
    backend = LocalStorage(base_dir=tmp_path / "uploads")

    src = tmp_path / "src.bin"
    payload = b"hello world" * 1000  # 11000 bytes
    src.write_bytes(payload)

    backend.put("ab/cd/abcdef.bin", src)
    out = backend.get_range("ab/cd/abcdef.bin", 0, len(payload) - 1)
    assert out == payload


def test_local_storage_get_size(tmp_path):
    from flexlog.storage.local import LocalStorage
    backend = LocalStorage(base_dir=tmp_path / "uploads")
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 500)
    backend.put("aa/bb/foo.bin", src)
    assert backend.get_size("aa/bb/foo.bin") == 500


def test_local_storage_exists_true_and_false(tmp_path):
    from flexlog.storage.local import LocalStorage
    backend = LocalStorage(base_dir=tmp_path / "uploads")
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    backend.put("aa/bb/here.bin", src)
    assert backend.exists("aa/bb/here.bin")
    assert not backend.exists("aa/bb/missing.bin")


def test_local_storage_delete(tmp_path):
    from flexlog.storage.local import LocalStorage
    backend = LocalStorage(base_dir=tmp_path / "uploads")
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    backend.put("aa/bb/doomed.bin", src)
    assert backend.exists("aa/bb/doomed.bin")
    backend.delete("aa/bb/doomed.bin")
    assert not backend.exists("aa/bb/doomed.bin")


def test_local_storage_get_range_partial(tmp_path):
    """get_range(start, end) returns exactly bytes [start, end] inclusive."""
    from flexlog.storage.local import LocalStorage
    backend = LocalStorage(base_dir=tmp_path / "uploads")
    src = tmp_path / "src.bin"
    src.write_bytes(b"0123456789")
    backend.put("aa/bb/range.bin", src)
    assert backend.get_range("aa/bb/range.bin", 0, 0) == b"0"
    assert backend.get_range("aa/bb/range.bin", 2, 5) == b"2345"
    assert backend.get_range("aa/bb/range.bin", 9, 9) == b"9"


def test_local_storage_put_creates_shard_dirs(tmp_path):
    """The aa/bb/ shard directories must be created if absent."""
    from flexlog.storage.local import LocalStorage
    base = tmp_path / "uploads"
    backend = LocalStorage(base_dir=base)
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    backend.put("ef/12/abc.bin", src)
    assert (base / "ef" / "12" / "abc.bin").exists()


def test_factory_returns_local_storage_by_default(monkeypatch, tmp_path):
    """get_storage() with FLEXLOG_STORAGE_BACKEND unset → LocalStorage."""
    monkeypatch.delenv("FLEXLOG_STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    from flexlog.storage import get_storage
    from flexlog.storage.local import LocalStorage
    storage = get_storage()
    assert isinstance(storage, LocalStorage)


def test_factory_returns_local_storage_when_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_STORAGE_BACKEND", "local")
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    from flexlog.storage import get_storage
    from flexlog.storage.local import LocalStorage
    assert isinstance(get_storage(), LocalStorage)


def test_local_storage_delete_missing_is_noop(tmp_path):
    """Protocol contract: missing key is not an error."""
    from flexlog.storage.local import LocalStorage
    backend = LocalStorage(base_dir=tmp_path / "uploads")
    backend.delete("aa/bb/never-existed.bin")  # must not raise
