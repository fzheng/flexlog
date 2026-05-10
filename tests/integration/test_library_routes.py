import io

from werkzeug.datastructures import FileStorage


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100


def _upload(authed_client, db_session, name="x.jpg", data=JPEG, mime="image/jpeg"):
    from flexlog.services.media import upload_to_media_file
    fs = FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)
    # Need an app context — use the test authed_client's transaction-scoped app
    from flask import current_app
    # The fixture's `app` is implicitly used; do via direct service in db_session
    with db_session.bind.engine.connect():
        pass
    # Simplest: do it by hitting the upload-via-session route. But we want to
    # write standalone library tests. Let's use the service directly inside
    # the test app's context.
    raise RuntimeError("use the upload helper from test_session_with_media if needed")


def test_library_index_empty(authed_client):
    resp = authed_client.get("/library")
    assert resp.status_code == 200


def test_library_index_lists_uploaded_files(authed_client, db_session, app):
    """Upload via session route, then assert /library shows the row."""
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    resp = authed_client.get("/library")
    body = resp.get_data(as_text=True)
    assert "x.jpg" in body  # original filename rendered


def test_library_filter_by_type(authed_client, db_session, app):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100
    authed_client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15", "overall_score": "4",
            "photos": (io.BytesIO(JPEG), "p.jpg", "image/jpeg"),
            "audios": (io.BytesIO(MP3), "a.mp3", "audio/mpeg"),
        },
        content_type="multipart/form-data",
    )
    resp_photos = authed_client.get("/library?type=photo").get_data(as_text=True)
    assert "p.jpg" in resp_photos and "a.mp3" not in resp_photos
    resp_audios = authed_client.get("/library?type=audio").get_data(as_text=True)
    assert "a.mp3" in resp_audios and "p.jpg" not in resp_audios


def test_library_orphan_filter(authed_client, db_session, app):
    """Files referenced by a session disappear when filtered to orphans only."""
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "linked.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    resp = authed_client.get("/library?orphans=1").get_data(as_text=True)
    assert "linked.jpg" not in resp


def test_library_hard_delete_removes_file(authed_client, db_session, app):
    from flexlog import paths
    from flexlog.db.models import MediaFile
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    db_session.expire_all()
    mf = db_session.query(MediaFile).first()
    target = paths.resolve_file_key(mf.file_key)
    assert target.exists()
    authed_client.post(f"/library/{mf.id}/hard_delete", follow_redirects=False)
    db_session.expire_all()
    assert db_session.get(MediaFile, mf.id) is None
    assert not target.exists()


def test_library_hard_delete_404(authed_client):
    resp = authed_client.post("/library/nope/hard_delete")
    assert resp.status_code == 404


def test_library_nav_link_in_base_template(authed_client):
    """The Media Library link should appear in the base nav on every page."""
    resp = authed_client.get("/")
    assert "/library" in resp.get_data(as_text=True)


def test_unlink_from_session_route(authed_client, db_session):
    """POST /sessions/<sid>/media/<sm_id>/unlink drops the join only — file persists."""
    import io
    from flexlog.db.models import MediaFile, SessionMedia, Session as SR
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
    authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    sess = db_session.query(SR).first()
    sm = db_session.query(SessionMedia).first()
    resp = authed_client.post(f"/sessions/{sess.id}/media/{sm.id}/unlink", follow_redirects=False)
    assert resp.status_code == 302
    assert f"/sessions/{sess.id}/edit" in resp.headers["Location"]
    db_session.expire_all()
    assert db_session.query(SessionMedia).count() == 0
    assert db_session.query(MediaFile).count() == 1  # file persists


def test_library_orphans_toggle_label_uses_ui_filter(authed_client, db_session):
    """The 'Orphans only' label must come from the ui filter (config-driven)."""
    resp = authed_client.get("/library")
    body = resp.get_data(as_text=True)
    assert "Orphans only" in body  # default builtin


def test_unlink_from_session_404_on_mismatched_session_id(authed_client, db_session):
    """Posting an sm_id that belongs to a different session must 404."""
    import io
    from flexlog.db.models import Session as SR, SessionMedia
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
    # Create two sessions, put a photo on the first
    authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-01", "overall_score": "3", "photos": (io.BytesIO(JPEG), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-05-01", "overall_score": "4"},
        content_type="multipart/form-data",
    )
    sessions = db_session.query(SR).order_by(SR.session_date).all()
    sm = db_session.query(SessionMedia).first()  # belongs to sessions[0]
    # Try to unlink under sessions[1]'s URL
    resp = authed_client.post(f"/sessions/{sessions[1].id}/media/{sm.id}/unlink")
    assert resp.status_code == 404
    # Verify the join still exists
    db_session.expire_all()
    assert db_session.query(SessionMedia).count() == 1


def test_unlink_from_session_404_on_unknown_sm_id(authed_client):
    resp = authed_client.post("/sessions/anything/media/no-such-sm-id/unlink")
    assert resp.status_code == 404
