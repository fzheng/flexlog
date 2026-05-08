import os
from pathlib import Path

import pytest

from flexlog import paths
from flexlog.paths import (
    DataDirError,
    config_path,
    data_dir,
    db_path,
    ensure_layout,
    tmp_uploads_dir,
    uploads_dir,
)


def test_data_dir_unset_raises(monkeypatch):
    monkeypatch.delenv("FLEXLOG_DATA_DIR", raising=False)
    with pytest.raises(DataDirError, match="FLEXLOG_DATA_DIR is not set"):
        data_dir()


def test_data_dir_empty_raises(monkeypatch):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", "")
    with pytest.raises(DataDirError, match="FLEXLOG_DATA_DIR is not set"):
        data_dir()


def test_data_dir_relative_raises(monkeypatch):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", "relative/path")
    with pytest.raises(DataDirError, match="must be an absolute path"):
        data_dir()


def test_data_dir_missing_raises(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(missing))
    with pytest.raises(DataDirError, match="does not exist"):
        data_dir()


def test_data_dir_not_a_directory_raises(monkeypatch, tmp_path):
    f = tmp_path / "not-a-dir"
    f.write_text("oops")
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(f))
    with pytest.raises(DataDirError, match="is not a directory"):
        data_dir()


def test_data_dir_unwritable_raises(monkeypatch, tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o500)  # read+execute only
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(d))
    try:
        with pytest.raises(DataDirError, match="not writable"):
            data_dir()
    finally:
        d.chmod(0o700)  # restore so tmp_path cleanup works


def test_data_dir_happy_returns_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    got = data_dir()
    assert got == tmp_path
    assert isinstance(got, Path)


def test_child_paths_are_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    assert db_path() == tmp_path / "data" / "encounters.db"
    assert config_path() == tmp_path / "config.json"
    assert uploads_dir() == tmp_path / "uploads"
    assert tmp_uploads_dir() == tmp_path / "uploads" / ".tmp"


def test_ensure_layout_creates_missing_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "uploads").is_dir()
    assert (tmp_path / "uploads" / ".tmp").is_dir()


def test_ensure_layout_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    ensure_layout()
    # Drop a sentinel file inside; second call must not wipe it.
    sentinel = tmp_path / "data" / "sentinel.txt"
    sentinel.write_text("keep me")
    ensure_layout()
    assert sentinel.read_text() == "keep me"
