import io

from werkzeug.datastructures import FileStorage

from flexlog.services.media import upload_to_media_file


JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100


def _upload(app, db_session, data=JPEG_BYTES, mime="image/jpeg", name="x.jpg"):
    fs = FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)
    with app.app_context():
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
    return mf


def test_serve_uploaded_file(authed_client, app, db_session):
    mf = _upload(app, db_session)
    resp = authed_client.get(f"/media/{mf.file_key}")
    assert resp.status_code == 200
    assert resp.data == JPEG_BYTES
    assert resp.mimetype == "image/jpeg"


def test_serve_traversal_attempt_404(authed_client):
    resp = authed_client.get("/media/../../etc/passwd")
    # Werkzeug normalizes '..' but our route still rejects via resolve_file_key
    assert resp.status_code in (400, 403, 404)


def test_serve_unknown_file_404(authed_client):
    # Valid-looking but non-existent file_key
    bogus_key = "ab/cd/" + ("0" * 64) + ".jpg"
    resp = authed_client.get(f"/media/{bogus_key}")
    assert resp.status_code == 404


def test_serve_absolute_path_in_key_404(authed_client):
    resp = authed_client.get("/media/%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------- Range header edge cases


def test_serve_range_malformed_header_416(authed_client, app, db_session):
    mf = _upload(app, db_session)
    resp = authed_client.get(
        f"/media/{mf.file_key}", headers={"Range": "garbage-not-a-range"}
    )
    assert resp.status_code == 416


def test_serve_range_both_empty_416(authed_client, app, db_session):
    """`Range: bytes=-` with neither start nor end is invalid."""
    mf = _upload(app, db_session)
    resp = authed_client.get(
        f"/media/{mf.file_key}", headers={"Range": "bytes=-"}
    )
    assert resp.status_code == 416


def test_serve_range_start_past_end_416(authed_client, app, db_session):
    """`Range: bytes=1000000-` where 1000000 > file size → 416 with
    Content-Range: bytes */<size> per RFC 7233."""
    mf = _upload(app, db_session)
    resp = authed_client.get(
        f"/media/{mf.file_key}", headers={"Range": "bytes=1000000-"}
    )
    assert resp.status_code == 416
    assert "Content-Range" in resp.headers


def test_serve_range_suffix_returns_last_n_bytes(authed_client, app, db_session):
    """`Range: bytes=-N` returns the last N bytes of the plaintext."""
    mf = _upload(app, db_session)
    resp = authed_client.get(
        f"/media/{mf.file_key}", headers={"Range": "bytes=-32"}
    )
    assert resp.status_code == 206
    assert len(resp.get_data()) == 32


def test_serve_range_clamps_end_past_size(authed_client, app, db_session):
    """`Range: bytes=10-99999` where 99999 > size → end clamped to size-1."""
    mf = _upload(app, db_session)
    resp = authed_client.get(
        f"/media/{mf.file_key}", headers={"Range": "bytes=10-99999"}
    )
    # Must return 206 with bytes from offset 10 to EOF (not 416)
    assert resp.status_code == 206
