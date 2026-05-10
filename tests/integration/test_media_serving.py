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
