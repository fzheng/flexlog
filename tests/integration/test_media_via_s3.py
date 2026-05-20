"""End-to-end: encrypt a file, store via S3Storage, range-decrypt
chunks back, assert byte-equivalent plaintext.

This verifies the storage abstraction didn't break the chunked
AES-GCM format's range-read semantics."""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def s3_storage(tmp_path):
    """S3Storage instance backed by moto's in-memory S3."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        from flexlog.storage.s3 import S3Storage
        yield S3Storage(
            bucket="test-bucket",
            endpoint_url=None,
            region="us-east-1",
            access_key="testing",
            secret_key="testing",
            key_prefix="uploads/",
        )


def test_encrypt_via_s3_then_range_decrypt_round_trips(s3_storage, tmp_path):
    """Encrypt 200 KB → put to S3 → range-decrypt chunks via
    storage.get_range → plaintext matches."""
    from flexlog.crypto import (
        FILE_HEADER_SIZE, encrypt_file_to_path, parse_header,
        derive_chunk_nonce, derive_fek, GCM_TAG_LEN,
    )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    plaintext = (b"abcdefghij" * 1024) * 20  # 200 KB
    src = tmp_path / "src.bin"
    src.write_bytes(plaintext)

    enc_tmp = tmp_path / "src.bin.enc"
    master_key = b"\x00" * 32
    file_sha = "a" * 64
    encrypt_file_to_path(src, enc_tmp, master_key, file_sha=file_sha)

    s3_storage.put("aa/bb/test.bin", enc_tmp)

    # Range-decrypt: re-fetch header + each chunk + decrypt
    header_bytes = s3_storage.get_range("aa/bb/test.bin", 0, FILE_HEADER_SIZE - 1)
    header = parse_header(header_bytes)
    fek = derive_fek(master_key, file_sha)
    aead = AESGCM(fek)

    out = bytearray()
    cs = header.chunk_size
    enc_chunk_full = cs + GCM_TAG_LEN
    for i in range(header.total_chunks):
        if i == header.total_chunks - 1:
            enc_len = (header.plaintext_size - i * cs) + GCM_TAG_LEN
        else:
            enc_len = enc_chunk_full
        offset = FILE_HEADER_SIZE + i * enc_chunk_full
        ct = s3_storage.get_range("aa/bb/test.bin", offset, offset + enc_len - 1)
        nonce = derive_chunk_nonce(master_key, file_sha, i)
        aad = i.to_bytes(4, "big")
        out.extend(aead.decrypt(nonce, ct, aad))

    assert bytes(out) == plaintext
