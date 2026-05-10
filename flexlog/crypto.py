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


# =========================================================================
# Chunked AES-GCM file format
# =========================================================================
#
# Header (16 bytes plaintext at file start):
#   magic[4]          = b"FLE0"
#   version[1]        = 0x01
#   chunk_size[3]     = uint24-be — chunk_size in bytes (default 65536)
#   plaintext_size[8] = uint64-be — original file size
#
# Body — N = ceil(plaintext_size / chunk_size) chunks:
#   per chunk i in [0, N):
#     ciphertext[chunk_size]   (last chunk may be shorter)
#     tag[16]                   (AES-GCM auth tag)
#
# Per-chunk nonce: HKDF(master, "flexlog/nonce/v1" || file_sha || chunk_index_u32be)[:12]
# Per-file FEK:    HKDF(master, "flexlog/fek/v1" || file_sha, 32)
# Associated data per chunk: chunk_index_u32be (binds the chunk to its position)

MAGIC = b"FLE0"
VERSION_BYTE = 1
DEFAULT_CHUNK_SIZE = 64 * 1024
FILE_HEADER_SIZE = 16
GCM_TAG_LEN = 16


@dataclass(frozen=True)
class FileHeader:
    magic: bytes
    version: int
    chunk_size: int
    plaintext_size: int

    @property
    def total_chunks(self) -> int:
        if self.plaintext_size == 0:
            return 0
        return (self.plaintext_size + self.chunk_size - 1) // self.chunk_size


def build_header(plaintext_size: int, chunk_size: int = DEFAULT_CHUNK_SIZE) -> bytes:
    if not (0 < chunk_size < (1 << 24)):
        raise ValueError("chunk_size must fit in 24 bits and be positive")
    if plaintext_size < 0 or plaintext_size > (1 << 63) - 1:
        raise ValueError("plaintext_size out of range")
    # chunk_size as uint24 big-endian
    cs_be = chunk_size.to_bytes(3, "big")
    return MAGIC + bytes([VERSION_BYTE]) + cs_be + plaintext_size.to_bytes(8, "big")


def parse_header(raw: bytes) -> FileHeader:
    if len(raw) < FILE_HEADER_SIZE:
        raise ValueError("header too short")
    magic = raw[0:4]
    if magic != MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    version = raw[4]
    if version != VERSION_BYTE:
        raise ValueError(f"unsupported file version {version}")
    chunk_size = int.from_bytes(raw[5:8], "big")
    plaintext_size = int.from_bytes(raw[8:16], "big")
    return FileHeader(magic=magic, version=version, chunk_size=chunk_size, plaintext_size=plaintext_size)


def derive_fek(master_key: bytes, file_sha_hex: str) -> bytes:
    """Per-file encryption key. Deterministic — same plaintext on this
    install always encrypts to the same ciphertext (preserves dedup)."""
    return hkdf_subkey(master_key, b"flexlog/fek/v1" + bytes.fromhex(file_sha_hex), 32)


def derive_chunk_nonce(master_key: bytes, file_sha_hex: str, chunk_index: int) -> bytes:
    """Per-chunk AES-GCM nonce. 12 bytes derived via HKDF — unique per
    (install, file, chunk_index)."""
    info = b"flexlog/nonce/v1" + bytes.fromhex(file_sha_hex) + chunk_index.to_bytes(4, "big")
    return hkdf_subkey(master_key, info, 12)


def encrypt_file_to_path(src_path, dst_path, master_key: bytes, file_sha: str,
                         chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
    """Encrypt the contents of `src_path` to `dst_path` using a per-file
    FEK + per-chunk nonces derived from (master_key, file_sha)."""
    fek = derive_fek(master_key, file_sha)
    aead = AESGCM(fek)
    src_size = _path(src_path).stat().st_size
    header = build_header(src_size, chunk_size)
    with _path(src_path).open("rb") as src, _path(dst_path).open("wb") as dst:
        dst.write(header)
        chunk_index = 0
        while True:
            chunk = src.read(chunk_size)
            if not chunk and chunk_index > 0:
                break
            if not chunk and chunk_index == 0:
                # Zero-byte input — nothing more to write
                break
            nonce = derive_chunk_nonce(master_key, file_sha, chunk_index)
            aad = chunk_index.to_bytes(4, "big")
            ct = aead.encrypt(nonce, chunk, aad)
            dst.write(ct)  # ct already includes the 16-byte tag
            chunk_index += 1


def decrypt_file_full(enc_path, master_key: bytes, file_sha: str) -> bytes:
    """Decrypt the entire encrypted file. Returns plaintext bytes.
    Raises InvalidPassword on any chunk auth failure."""
    fek = derive_fek(master_key, file_sha)
    aead = AESGCM(fek)
    with _path(enc_path).open("rb") as f:
        header = parse_header(f.read(FILE_HEADER_SIZE))
        if header.plaintext_size == 0:
            return b""
        out = bytearray()
        enc_chunk_full = header.chunk_size + GCM_TAG_LEN
        for i in range(header.total_chunks):
            if i == header.total_chunks - 1:
                # Last chunk may be partial
                remainder = header.plaintext_size - i * header.chunk_size
                enc_len = remainder + GCM_TAG_LEN
            else:
                enc_len = enc_chunk_full
            ct = f.read(enc_len)
            nonce = derive_chunk_nonce(master_key, file_sha, i)
            aad = i.to_bytes(4, "big")
            try:
                pt = aead.decrypt(nonce, ct, aad)
            except InvalidTag as e:
                raise InvalidPassword(f"chunk {i} auth failed") from e
            out.extend(pt)
        return bytes(out)


def decrypt_file_range(enc_path, master_key: bytes, file_sha: str,
                       start: int, end: int) -> bytes:
    """Decrypt the byte range [start, end] (inclusive on both ends) from
    the encrypted file. Returns exactly (end - start + 1) bytes. Decrypts
    ONLY the chunks intersecting the requested range."""
    fek = derive_fek(master_key, file_sha)
    aead = AESGCM(fek)
    with _path(enc_path).open("rb") as f:
        header = parse_header(f.read(FILE_HEADER_SIZE))
        if end >= header.plaintext_size:
            raise ValueError(f"range end {end} >= plaintext_size {header.plaintext_size}")
        if start < 0 or start > end:
            raise ValueError(f"invalid range start={start} end={end}")

        cs = header.chunk_size
        first_chunk = start // cs
        last_chunk = end // cs
        enc_chunk_full = cs + GCM_TAG_LEN

        # Seek to first encrypted chunk
        f.seek(FILE_HEADER_SIZE + first_chunk * enc_chunk_full)

        out = bytearray()
        for i in range(first_chunk, last_chunk + 1):
            if i == header.total_chunks - 1:
                remainder = header.plaintext_size - i * cs
                enc_len = remainder + GCM_TAG_LEN
            else:
                enc_len = enc_chunk_full
            ct = f.read(enc_len)
            nonce = derive_chunk_nonce(master_key, file_sha, i)
            aad = i.to_bytes(4, "big")
            try:
                pt = aead.decrypt(nonce, ct, aad)
            except InvalidTag as e:
                raise InvalidPassword(f"chunk {i} auth failed") from e
            # Trim first/last chunk to exact requested range
            lo = (start % cs) if i == first_chunk else 0
            hi = ((end % cs) + 1) if i == last_chunk else len(pt)
            out.extend(pt[lo:hi])
        return bytes(out)


def _path(p):
    """Coerce str or Path to Path."""
    from pathlib import Path
    return p if isinstance(p, Path) else Path(p)
