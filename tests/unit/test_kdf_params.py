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


def test_write_kdf_params_creates_file_with_mode_0600(tmp_path):
    """The file (and the tmp file during write) must be mode 0600 — the
    plaintext sidecar contains the wrapped master key + Argon2 salt + KDF
    params and shouldn't be world-readable, even momentarily."""
    import os
    import stat
    params = KdfParams(
        version=1, kek_salt=b"\x01" * 16, kek_nonce=b"\x02" * 12,
        wrapped_master_key=b"\x03" * 48,
        argon2_time=4, argon2_memory_kib=65536, argon2_parallelism=2,
    )
    path = tmp_path / "kdf_params.json"
    write_kdf_params(path, params)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"expected 0o600, got 0o{mode:o}"


def test_write_kdf_params_tmp_file_uses_O_EXCL(tmp_path, monkeypatch):
    """Tmp file creation uses O_EXCL so an attacker can't pre-create the
    tmp path with a symlink. Verify by monkey-patching os.open and
    inspecting the flags."""
    import os
    real_open = os.open
    captured_flags = []

    def spy_open(path, flags, *args):
        # Track flags only when called for files inside tmp_path (skip
        # other implicit opens like Python's import machinery)
        if str(path).startswith(str(tmp_path)):
            captured_flags.append(flags)
        return real_open(path, flags, *args)

    monkeypatch.setattr(os, "open", spy_open)

    params = KdfParams(
        version=1, kek_salt=b"\x01" * 16, kek_nonce=b"\x02" * 12,
        wrapped_master_key=b"\x03" * 48,
        argon2_time=4, argon2_memory_kib=65536, argon2_parallelism=2,
    )
    write_kdf_params(tmp_path / "kdf_params.json", params)

    # At least one os.open call inside tmp_path should have O_EXCL + O_CREAT
    flagged = [f for f in captured_flags
               if (f & os.O_CREAT) and (f & os.O_EXCL)]
    assert flagged, (
        f"no os.open(..., O_CREAT|O_EXCL, ...) call observed. "
        f"flags seen: {[oct(f) for f in captured_flags]}"
    )
