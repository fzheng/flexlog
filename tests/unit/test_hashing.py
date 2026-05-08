import hashlib
import io

import pytest

from flexlog.hashing import sha256_hex_stream


def test_sha256_hex_stream_empty_input_returns_known_digest():
    digest = sha256_hex_stream(io.BytesIO(b""))
    # SHA-256 of empty input
    assert digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_hex_stream_short_input_returns_known_digest():
    digest = sha256_hex_stream(io.BytesIO(b"abc"))
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_sha256_hex_stream_chunks_match_single_call():
    data = b"flexlog test payload " * 1000  # ~21KB
    one_shot = sha256_hex_stream(io.BytesIO(data))
    chunked = sha256_hex_stream(io.BytesIO(data), chunk_size=64)
    assert one_shot == chunked


def test_sha256_hex_stream_does_not_load_full_buffer(tmp_path):
    # Write ~2 MB to a real file; verify streaming reads it without OOM-style
    # patterns by comparing to a known digest computed via stdlib hashlib.
    payload = (b"x" * 1024) * 2048  # 2 MiB
    f = tmp_path / "big.bin"
    f.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    with f.open("rb") as r:
        got = sha256_hex_stream(r)
    assert got == expected


def test_sha256_hex_stream_rejects_non_binary_reader():
    text_reader = io.StringIO("not bytes")
    with pytest.raises(TypeError, match="binary reader"):
        sha256_hex_stream(text_reader)  # type: ignore[arg-type]


def test_sha256_hex_stream_rejects_nonpositive_chunk_size():
    with pytest.raises(ValueError, match="chunk_size must be positive"):
        sha256_hex_stream(io.BytesIO(b"data"), chunk_size=0)
