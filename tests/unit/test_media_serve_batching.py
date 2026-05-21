"""Media serving batches storage.get_range calls so a single browser
Range request maps to ONE storage GET (instead of one per AES-GCM
chunk). This is the difference between smooth video playback and
stuttering on a cloud backend where each storage GET costs a round
trip."""
from __future__ import annotations

from pathlib import Path


def _count_storage_calls(real_storage):
    """Wrap a real storage backend with a counter on get_range."""
    class _Counted:
        def __init__(self, inner):
            self.inner = inner
            self.get_range_calls = 0

        def get_range(self, file_key, start, end):
            self.get_range_calls += 1
            return self.inner.get_range(file_key, start, end)

        def __getattr__(self, name):
            return getattr(self.inner, name)
    return _Counted(real_storage)


def _encrypt_and_put(storage, plaintext: bytes, master_key: bytes,
                     file_sha: str, tmp_path: Path) -> str:
    """Encrypt `plaintext` and put it into `storage` under a deterministic
    file_key. Returns the file_key."""
    from flexlog.crypto import encrypt_file_to_path
    src = tmp_path / "plain.bin"
    src.write_bytes(plaintext)
    enc = tmp_path / "enc.bin"
    encrypt_file_to_path(src, enc, master_key, file_sha=file_sha)
    file_key = f"{file_sha[:2]}/{file_sha[2:4]}/{file_sha}.bin"
    storage.put(file_key, enc)
    return file_key


def test_range_response_uses_one_storage_get_per_request(tmp_path):
    """A Range request spanning 16 AES-GCM chunks should result in a
    single storage.get_range call (8 MiB batch comfortably covers
    16 × 64 KiB chunks)."""
    from flexlog.crypto import (
        FILE_HEADER_SIZE, GCM_TAG_LEN, parse_header,
    )
    from flexlog.storage.local import LocalStorage
    from flexlog.web.media_bp import _stream_range

    # 16 chunks of plaintext = 1 MiB
    chunk_size = 64 * 1024  # default in flexlog.crypto
    plaintext = bytes(range(256)) * (chunk_size * 16 // 256)
    assert len(plaintext) == chunk_size * 16

    master_key = b"\xab" * 32
    file_sha = "a" * 64
    raw = LocalStorage(base_dir=tmp_path / "uploads")
    storage = _count_storage_calls(raw)
    file_key = _encrypt_and_put(
        storage.inner, plaintext, master_key, file_sha, tmp_path,
    )

    # Read header (not counted toward range fetch)
    header_bytes = storage.inner.get_range(file_key, 0, FILE_HEADER_SIZE - 1)
    header = parse_header(header_bytes)

    # Now consume the full plaintext via the streaming helper and count
    # storage.get_range calls. The 16-chunk Range fits comfortably in
    # one 8 MiB batch.
    storage.get_range_calls = 0
    out = b"".join(_stream_range(
        storage, file_key, header, master_key, file_sha,
        start=0, end=len(plaintext) - 1,
    ))
    assert out == plaintext
    assert storage.get_range_calls == 1, (
        "expected one batched fetch, got "
        f"{storage.get_range_calls} (regression on chunk-by-chunk fetching)"
    )


def test_range_response_sets_cache_control(authed_client, app, db_session):
    """Media responses must carry Cache-Control: private + immutable
    so the browser caches video segments instead of re-fetching every
    seek/replay. file_keys are SHA-content-addressed → the bytes are
    immutable for a given key."""
    import io
    from werkzeug.datastructures import FileStorage
    from flexlog.services.media import upload_to_media_file

    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 200
    fs = FileStorage(
        stream=io.BytesIO(jpeg), filename="x.jpg", content_type="image/jpeg",
    )
    with app.app_context():
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()

    resp = authed_client.get(
        f"/media/{mf.file_key}", headers={"Range": "bytes=0-99"},
    )
    assert resp.status_code == 206
    cc = resp.headers.get("Cache-Control", "")
    assert "private" in cc
    assert "immutable" in cc
    assert "max-age" in cc
