"""Unit tests for flexlog.crypto — primitive operations."""
from __future__ import annotations

import pytest

from flexlog.crypto import (
    ARGON2_DEFAULT_PARAMS,
    InvalidPassword,
    aes_gcm_unwrap,
    aes_gcm_wrap,
    argon2id_kek,
    hkdf_subkey,
)


def test_argon2id_kek_deterministic_for_same_salt_and_params():
    salt = b"\x00" * 16
    kek1 = argon2id_kek("hunter2", salt, ARGON2_DEFAULT_PARAMS)
    kek2 = argon2id_kek("hunter2", salt, ARGON2_DEFAULT_PARAMS)
    assert kek1 == kek2
    assert len(kek1) == 32


def test_argon2id_kek_differs_for_different_salt():
    p = "hunter2"
    kek1 = argon2id_kek(p, b"\x00" * 16, ARGON2_DEFAULT_PARAMS)
    kek2 = argon2id_kek(p, b"\x01" * 16, ARGON2_DEFAULT_PARAMS)
    assert kek1 != kek2


def test_argon2id_kek_differs_for_different_password():
    salt = b"\x00" * 16
    k1 = argon2id_kek("hunter2", salt, ARGON2_DEFAULT_PARAMS)
    k2 = argon2id_kek("hunter3", salt, ARGON2_DEFAULT_PARAMS)
    assert k1 != k2


def test_aes_gcm_wrap_unwrap_roundtrip():
    import os
    kek = os.urandom(32)
    nonce = os.urandom(12)
    plaintext = b"the master key bytes here, 32 of them total....."[:32]
    blob = aes_gcm_wrap(kek, nonce, plaintext)
    # blob is ciphertext+tag = 32 + 16 = 48 bytes
    assert len(blob) == 48
    recovered = aes_gcm_unwrap(kek, nonce, blob)
    assert recovered == plaintext


def test_aes_gcm_unwrap_with_wrong_key_raises_invalid_password():
    import os
    nonce = os.urandom(12)
    blob = aes_gcm_wrap(b"\x00" * 32, nonce, b"x" * 32)
    with pytest.raises(InvalidPassword):
        aes_gcm_unwrap(b"\xff" * 32, nonce, blob)


def test_aes_gcm_unwrap_with_tampered_blob_raises_invalid_password():
    import os
    kek = os.urandom(32)
    nonce = os.urandom(12)
    blob = aes_gcm_wrap(kek, nonce, b"x" * 32)
    # Flip a byte in the middle
    tampered = blob[:10] + bytes([blob[10] ^ 0xFF]) + blob[11:]
    with pytest.raises(InvalidPassword):
        aes_gcm_unwrap(kek, nonce, tampered)


def test_hkdf_subkey_deterministic():
    master = b"\x42" * 32
    k1 = hkdf_subkey(master, b"flexlog/sqlcipher/v1", 32)
    k2 = hkdf_subkey(master, b"flexlog/sqlcipher/v1", 32)
    assert k1 == k2
    assert len(k1) == 32


def test_hkdf_subkey_different_for_different_info():
    master = b"\x42" * 32
    k1 = hkdf_subkey(master, b"flexlog/sqlcipher/v1", 32)
    k2 = hkdf_subkey(master, b"flexlog/fek/v1", 32)
    assert k1 != k2


def test_hkdf_subkey_respects_length():
    master = b"\x42" * 32
    assert len(hkdf_subkey(master, b"x", 16)) == 16
    assert len(hkdf_subkey(master, b"x", 48)) == 48


# ---------------------------------------------------------- Chunked AEAD

from pathlib import Path

from flexlog.crypto import (
    FILE_HEADER_SIZE,
    DEFAULT_CHUNK_SIZE,
    encrypt_file_to_path,
    decrypt_file_full,
    decrypt_file_range,
    parse_header,
)


def _master() -> bytes:
    return b"\x42" * 32


def test_encrypt_decrypt_zero_byte_file(tmp_path):
    src = tmp_path / "in.bin"; src.write_bytes(b"")
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="a" * 64)
    pt = decrypt_file_full(dst, _master(), file_sha="a" * 64)
    assert pt == b""


def test_encrypt_decrypt_one_byte_file(tmp_path):
    src = tmp_path / "in.bin"; src.write_bytes(b"X")
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="b" * 64)
    pt = decrypt_file_full(dst, _master(), file_sha="b" * 64)
    assert pt == b"X"


def test_encrypt_decrypt_exactly_one_chunk(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"A" * DEFAULT_CHUNK_SIZE)
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="c" * 64)
    pt = decrypt_file_full(dst, _master(), file_sha="c" * 64)
    assert pt == b"A" * DEFAULT_CHUNK_SIZE


def test_encrypt_decrypt_one_and_half_chunks(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"A" * (DEFAULT_CHUNK_SIZE + DEFAULT_CHUNK_SIZE // 2))
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="d" * 64)
    pt = decrypt_file_full(dst, _master(), file_sha="d" * 64)
    assert pt == b"A" * (DEFAULT_CHUNK_SIZE + DEFAULT_CHUNK_SIZE // 2)


def test_header_well_formed(tmp_path):
    src = tmp_path / "in.bin"; src.write_bytes(b"hello world")
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="e" * 64)
    with dst.open("rb") as f:
        h = parse_header(f.read(FILE_HEADER_SIZE))
    assert h.magic == b"FLE0"
    assert h.version == 1
    assert h.chunk_size == DEFAULT_CHUNK_SIZE
    assert h.plaintext_size == len(b"hello world")


def test_corrupted_chunk_raises(tmp_path):
    src = tmp_path / "in.bin"
    src.write_bytes(b"some content here" * 100)
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="f" * 64)
    # Flip a byte well past the header
    blob = dst.read_bytes()
    pos = FILE_HEADER_SIZE + 5
    blob = blob[:pos] + bytes([blob[pos] ^ 0x01]) + blob[pos+1:]
    dst.write_bytes(blob)
    with pytest.raises(InvalidPassword):
        decrypt_file_full(dst, _master(), file_sha="f" * 64)


def test_range_within_first_chunk(tmp_path):
    pt_full = b"a" * 200 + b"b" * 200 + b"c" * 200
    src = tmp_path / "in.bin"; src.write_bytes(pt_full)
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="0" * 64)
    out = decrypt_file_range(dst, _master(), file_sha="0" * 64, start=10, end=99)
    assert out == pt_full[10:100]


def test_range_spans_chunk_boundary(tmp_path):
    # Pattern that lets us spot off-by-one
    pt_full = bytes(range(256)) * 1024  # 256 KiB
    src = tmp_path / "in.bin"; src.write_bytes(pt_full)
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="1" * 64)
    # Cross the 64 KB boundary exactly
    cs = DEFAULT_CHUNK_SIZE
    out = decrypt_file_range(dst, _master(), file_sha="1" * 64, start=cs - 5, end=cs + 4)
    assert out == pt_full[cs - 5 : cs + 5]


def test_range_to_eof(tmp_path):
    pt_full = b"X" * 1000
    src = tmp_path / "in.bin"; src.write_bytes(pt_full)
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="2" * 64)
    out = decrypt_file_range(dst, _master(), file_sha="2" * 64, start=500, end=999)
    assert out == pt_full[500:1000]


def test_range_zero_to_eof_equals_full_decrypt(tmp_path):
    pt_full = (bytes(range(256)) * 300)[:DEFAULT_CHUNK_SIZE + 1234]
    src = tmp_path / "in.bin"; src.write_bytes(pt_full)
    dst = tmp_path / "out.enc"
    encrypt_file_to_path(src, dst, _master(), file_sha="3" * 64)
    full = decrypt_file_full(dst, _master(), file_sha="3" * 64)
    ranged = decrypt_file_range(dst, _master(), file_sha="3" * 64, start=0, end=len(pt_full) - 1)
    assert full == pt_full
    assert ranged == pt_full


def test_encrypt_file_to_path_fsyncs_destination(tmp_path, monkeypatch):
    """encrypt_file_to_path must fsync the destination before returning,
    so a power loss between return and the kernel's natural flush
    doesn't leave a short/zero-length encrypted file on disk."""
    import os
    from flexlog.crypto import encrypt_file_to_path

    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.enc"
    src.write_bytes(b"hello world" * 1000)

    fsync_calls = []
    real_fsync = os.fsync
    def spy_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)
    monkeypatch.setattr("flexlog.crypto.os.fsync", spy_fsync)

    encrypt_file_to_path(src, dst, master_key=b"\x00" * 32, file_sha="a" * 64)

    assert len(fsync_calls) >= 1, "expected at least one os.fsync on the destination"
