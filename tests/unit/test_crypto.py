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
