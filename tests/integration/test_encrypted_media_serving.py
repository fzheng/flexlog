"""GET /media/<file_key> — encrypted-on-disk, plaintext-over-the-wire,
HTTP Range support intact."""
from __future__ import annotations

import io
from werkzeug.datastructures import FileStorage

from flexlog.services.media import upload_to_media_file

# Minimal valid JPEG (smallest bytes that pass our MIME + magic check)
_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000302020203020203030303040303040504080605050505"
    "0a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514ffc0000b08010001"
    "0101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b51000020103030204030"
    "505040400000177000102031104052131410613516107227114328191a1b1c10923334252f0156272d10a162434e125f1171819"
    "1a262728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788"
    "898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5"
    "e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbf3ffd9"
)


def _upload(db_session, content: bytes, name: str = "test.jpg"):
    fs = FileStorage(stream=io.BytesIO(content), filename=name, content_type="image/jpeg")
    mf = upload_to_media_file(db_session, fs)
    db_session.commit()
    return mf


def test_full_get_returns_plaintext(app, db_session, authed_client):
    mf = _upload(db_session, _JPEG)
    resp = authed_client.get(f"/media/{mf.file_key}")
    assert resp.status_code == 200
    assert resp.data == _JPEG


def test_range_request_returns_206_with_correct_bytes(app, db_session, authed_client):
    # Build a larger file so range is meaningful
    big = (_JPEG * 50)[:200_000]  # ~200 KB, exact bytes
    mf = _upload(db_session, big, name="big.jpg")
    resp = authed_client.get(f"/media/{mf.file_key}", headers={"Range": "bytes=1000-2999"})
    assert resp.status_code == 206
    assert resp.data == big[1000:3000]
    assert resp.headers["Content-Range"] == f"bytes 1000-2999/{len(big)}"
    assert resp.headers["Content-Length"] == "2000"
    assert resp.headers["Accept-Ranges"] == "bytes"


def test_range_spanning_chunk_boundary(app, db_session, authed_client):
    # Must start with JPEG magic to pass upload validation; pad with a
    # deterministic byte pattern to cross the 64 KB chunk boundary.
    big = _JPEG + (bytes(range(256)) * 1024)  # >256 KB, starts with ffd8ff
    mf = _upload(db_session, big, name="b.jpg")
    # Cross the 64 KB chunk boundary
    resp = authed_client.get(f"/media/{mf.file_key}", headers={"Range": "bytes=65530-65540"})
    assert resp.status_code == 206
    assert resp.data == big[65530:65541]


def test_range_past_eof_returns_416(app, db_session, authed_client):
    mf = _upload(db_session, _JPEG)
    resp = authed_client.get(f"/media/{mf.file_key}", headers={"Range": "bytes=9999999-99999999"})
    assert resp.status_code == 416


def test_open_ended_range_to_eof(app, db_session, authed_client):
    # _JPEG is ~334 bytes; need >=5000 to make the open-ended slice meaningful.
    big = (_JPEG * 20)[:5000]
    mf = _upload(db_session, big, name="b.jpg")
    resp = authed_client.get(f"/media/{mf.file_key}", headers={"Range": "bytes=4000-"})
    assert resp.status_code == 206
    assert resp.data == big[4000:5000]


def test_anonymous_still_blocked(client, app, db_session):
    mf = _upload(db_session, _JPEG)
    resp = client.get(f"/media/{mf.file_key}")
    assert resp.status_code == 303  # redirected to /
