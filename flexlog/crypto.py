"""Cryptographic primitives for flexlog's encryption-at-rest feature.

Three layers:
  * Argon2id-based KEK derivation from a user-typed password + salt.
  * AES-GCM wrap/unwrap of small secrets (master key, FEKs).
  * HKDF-based subkey derivation for SQLCipher passphrase, per-file FEKs,
    per-chunk nonces.

A separate chunked AES-GCM file format (encrypt entire file with
deterministic per-chunk nonces, range-decrypt by seeking to the relevant
chunks) is added in a later step in this module.

The module deliberately holds no Flask imports — keeps it testable with
plain bytes.
"""
from __future__ import annotations

from dataclasses import dataclass

import argon2.low_level as argon2_ll
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# ----------------------------------------------------------- KEK derivation

@dataclass(frozen=True)
class Argon2Params:
    time_cost: int      # iterations
    memory_kib: int     # memory in KiB (1 MiB = 1024)
    parallelism: int


ARGON2_DEFAULT_PARAMS = Argon2Params(time_cost=4, memory_kib=64 * 1024, parallelism=2)


def argon2id_kek(password: str, salt: bytes, params: Argon2Params) -> bytes:
    """Derive a 32-byte KEK from a password via Argon2id."""
    return argon2_ll.hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_kib,
        parallelism=params.parallelism,
        hash_len=32,
        type=argon2_ll.Type.ID,
    )


# ----------------------------------------------------------- AES-GCM wrap

class InvalidPassword(Exception):
    """Raised when an AES-GCM unwrap fails — i.e. the KEK is wrong, which
    in flexlog means the user-typed password was wrong (or the blob was
    tampered with). The caller should treat both cases identically: refuse
    the login attempt."""


def aes_gcm_wrap(key: bytes, nonce: bytes, plaintext: bytes,
                 associated_data: bytes | None = None) -> bytes:
    """Encrypt `plaintext` with AES-GCM. Returns ciphertext concatenated
    with the 16-byte auth tag (single blob)."""
    return AESGCM(key).encrypt(nonce, plaintext, associated_data)


def aes_gcm_unwrap(key: bytes, nonce: bytes, blob: bytes,
                   associated_data: bytes | None = None) -> bytes:
    """Decrypt `blob` (ciphertext + 16-byte tag) with AES-GCM. Raises
    `InvalidPassword` on any failure (wrong key OR tampered blob; we don't
    distinguish to avoid leaking which one)."""
    try:
        return AESGCM(key).decrypt(nonce, blob, associated_data)
    except InvalidTag as e:
        raise InvalidPassword("AES-GCM auth failed") from e


# ----------------------------------------------------------- HKDF subkeys

def hkdf_subkey(master_key: bytes, info: bytes, length: int) -> bytes:
    """Derive a subkey of `length` bytes from `master_key` for purpose `info`.
    No salt is used — `info` is the domain separator."""
    return HKDF(
        algorithm=SHA256(), length=length, salt=None, info=info,
    ).derive(master_key)
