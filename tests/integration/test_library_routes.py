import io

import pytest
from werkzeug.datastructures import FileStorage


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100


def _make_person(db_session, alias="Alice"):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias=alias, tag_input="")
    db_session.commit()
    return p


def _attach_photo(db_session, session_id, data=JPEG, filename="x.jpg", mime="image/jpeg"):
    """Upload a file via service layer and link it to the session."""
    from flexlog.services.media import upload_to_media_file
    from flexlog.services.sessions import link_media_to_session
    fs = FileStorage(stream=io.BytesIO(data), filename=filename, content_type=mime)
    mf = upload_to_media_file(db_session, fs)
    link_media_to_session(db_session, session_id, {"photo": [mf.file_key], "audio": [], "video": []})
    db_session.commit()
    return mf


def _attach_audio(db_session, session_id, data=MP3, filename="a.mp3", mime="audio/mpeg"):
    """Upload an audio file via service layer and link it to the session."""
    from flexlog.services.media import upload_to_media_file
    from flexlog.services.sessions import link_media_to_session
    fs = FileStorage(stream=io.BytesIO(data), filename=filename, content_type=mime)
    mf = upload_to_media_file(db_session, fs)
    link_media_to_session(db_session, session_id, {"photo": [], "audio": [mf.file_key], "video": []})
    db_session.commit()
    return mf


def _make_session(db_session, person_id, session_date="2026-04-15"):
    from flexlog.services.sessions import create_session
    s = create_session(db_session, person_id=person_id, session_date=session_date,
                       ratings={}, notes=None, link_urls=[])
    db_session.flush()
    return s


def test_library_index_empty(authed_client):
    resp = authed_client.get("/library")
    assert resp.status_code == 200


def test_library_index_lists_uploaded_files(authed_client, db_session):
    """Upload via service layer, then assert /library shows the row."""
    p = _make_person(db_session)
    s = _make_session(db_session, p.id)
    _attach_photo(db_session, s.id, filename="x.jpg")
    resp = authed_client.get("/library")
    body = resp.get_data(as_text=True)
    assert "x.jpg" in body  # original filename rendered


def test_library_filter_by_type(authed_client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id)
    _attach_photo(db_session, s.id, filename="p.jpg")
    # Use distinct bytes for MP3 to avoid dedup
    _attach_audio(db_session, s.id, data=MP3 + b"\x01", filename="a.mp3")

    resp_photos = authed_client.get("/library?type=photo").get_data(as_text=True)
    assert "p.jpg" in resp_photos and "a.mp3" not in resp_photos

    resp_audios = authed_client.get("/library?type=audio").get_data(as_text=True)
    assert "a.mp3" in resp_audios and "p.jpg" not in resp_audios


def test_library_orphan_filter(authed_client, db_session):
    """Files referenced by a session disappear when filtered to orphans only."""
    p = _make_person(db_session)
    s = _make_session(db_session, p.id)
    _attach_photo(db_session, s.id, filename="linked.jpg")
    resp = authed_client.get("/library?orphans=1").get_data(as_text=True)
    assert "linked.jpg" not in resp


def test_library_hard_delete_removes_file(authed_client, db_session):
    from flexlog import paths
    from flexlog.db.models import MediaFile
    p = _make_person(db_session)
    s = _make_session(db_session, p.id)
    mf = _attach_photo(db_session, s.id, filename="x.jpg")
    # Unlink first so the file becomes orphan-deletable via hard_delete
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
    """Service-layer attach then unlink route drops the join — file persists."""
    from flexlog.db.models import MediaFile, SessionMedia, Session as SR
    p = _make_person(db_session)
    s = _make_session(db_session, p.id)
    _attach_photo(db_session, s.id)
    db_session.expire_all()
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
    """A session_media id that belongs to a different session must 404."""
    from flexlog.db.models import Session as SR, SessionMedia
    p = _make_person(db_session)
    # Create two sessions; attach photo to the first
    s1 = _make_session(db_session, p.id, session_date="2026-04-01")
    _attach_photo(db_session, s1.id)
    s2 = _make_session(db_session, p.id, session_date="2026-05-01")
    db_session.commit()
    db_session.expire_all()
    sm = db_session.query(SessionMedia).first()  # belongs to s1
    # Try to unlink under s2's URL
    resp = authed_client.post(f"/sessions/{s2.id}/media/{sm.id}/unlink")
    assert resp.status_code == 404
    # Verify the join still exists
    db_session.expire_all()
    assert db_session.query(SessionMedia).count() == 1


def test_unlink_from_session_404_on_unknown_sm_id(authed_client):
    resp = authed_client.post("/sessions/anything/media/no-such-sm-id/unlink")
    assert resp.status_code == 404
