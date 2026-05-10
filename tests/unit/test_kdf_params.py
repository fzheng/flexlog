"""Unit tests for flexlog.kdf_params — the kdf_params.json sidecar."""
from __future__ import annotations

import json

import pytest

from flexlog.kdf_params import (
    KdfParams,
    CorruptKdfParamsError,
    load_kdf_params,
    write_kdf_params,
)


def test_write_then_read_roundtrip(tmp_path):
    params = KdfParams(
        version=1,
        kek_salt=b"\x01" * 16,
        kek_nonce=b"\x02" * 12,
        wrapped_master_key=b"\x03" * 48,
        argon2_time=4, argon2_memory_kib=65536, argon2_parallelism=2,
    )
    path = tmp_path / "kdf_params.json"
    write_kdf_params(path, params)
    got = load_kdf_params(path)
    assert got == params


def test_read_returns_none_if_missing(tmp_path):
    path = tmp_path / "no_such.json"
    assert load_kdf_params(path) is None


def test_read_raises_on_corrupt_json(tmp_path):
    path = tmp_path / "kdf_params.json"
    path.write_text("not json {{")
    with pytest.raises(CorruptKdfParamsError):
        load_kdf_params(path)


def test_read_raises_on_missing_fields(tmp_path):
    path = tmp_path / "kdf_params.json"
    path.write_text(json.dumps({"version": 1, "kek_salt": "00" * 16}))
    with pytest.raises(CorruptKdfParamsError):
        load_kdf_params(path)


def test_write_is_atomic(tmp_path, monkeypatch):
    """Crash between write-to-tmp and rename leaves only the original (or
    nothing), never a partial main file."""
    import os
    path = tmp_path / "kdf_params.json"
    params = KdfParams(
        version=1, kek_salt=b"\x01" * 16, kek_nonce=b"\x02" * 12,
        wrapped_master_key=b"\x03" * 48,
        argon2_time=4, argon2_memory_kib=65536, argon2_parallelism=2,
    )
    # Pre-populate with v1
    write_kdf_params(path, params)
    original = path.read_text()

    # Now simulate failure: monkey-patch os.replace to raise after write
    def boom(_a, _b):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)

    new_params = KdfParams(
        version=1, kek_salt=b"\xff" * 16, kek_nonce=b"\xee" * 12,
        wrapped_master_key=b"\xdd" * 48,
        argon2_time=4, argon2_memory_kib=65536, argon2_parallelism=2,
    )
    with pytest.raises(OSError):
        write_kdf_params(path, new_params)

    # Main file is still the original
    assert path.read_text() == original
    # And no orphan .tmp.<random> file was left behind in the directory
    # (the finally clause should have cleaned it up)
    leftover = [p for p in path.parent.iterdir() if p.name.startswith("." + path.name + ".tmp.")]
    assert leftover == [], f"orphan tmp files: {leftover}"
