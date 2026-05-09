import io

from werkzeug.datastructures import FileStorage


JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100


def _person(db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    return p


def test_create_session_with_one_photo(client, db_session):
    p = _person(db_session)
    data = {
        "session_date": "2026-04-15",
        "overall_score": "4",
        "photos": (io.BytesIO(JPEG_BYTES), "vacation.jpg", "image/jpeg"),
    }
    resp = client.post(f"/people/{p.id}/sessions", data=data, content_type="multipart/form-data", follow_redirects=False)
    assert resp.status_code == 302
    from flexlog.db.models import MediaFile, SessionMedia
    media_files = db_session.query(MediaFile).all()
    assert len(media_files) == 1
    assert media_files[0].media_type == "photo"
    joins = db_session.query(SessionMedia).all()
    assert len(joins) == 1


def test_dedup_when_same_bytes_uploaded_twice(client, db_session):
    p = _person(db_session)
    # First session with the photo
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "first.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    # Second session, same bytes, different filename
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-16", "overall_score": "5", "photos": (io.BytesIO(JPEG_BYTES), "second.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import MediaFile
    rows = db_session.query(MediaFile).all()
    assert len(rows) == 1, f"expected dedup; got {len(rows)} rows"
    assert rows[0].original_filename == "first.jpg"  # first-seen wins


def test_remove_existing_media_unlinks_join_only(client, db_session):
    """Editing a session with remove_session_media[<sm_id>] drops the join,
    leaves the file on disk + media_file row."""
    p = _person(db_session)
    # Create session with a photo
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import MediaFile, Session as SessionRow, SessionMedia
    sess = db_session.query(SessionRow).first()
    sm = db_session.query(SessionMedia).first()
    # Edit: remove the join
    resp = client.post(
        f"/sessions/{sess.id}",
        data={"session_date": "2026-04-15", "overall_score": "4", "remove_session_media": [sm.id]},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db_session.expire_all()
    assert db_session.query(SessionMedia).count() == 0
    assert db_session.query(MediaFile).count() == 1  # file persists


def test_link_thumbnail_attached(client, db_session):
    p = _person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15",
            "overall_score": "4",
            "link_url": ["https://example.com"],
            "link_label": ["Ref"],
            "link_thumbnail": [(io.BytesIO(JPEG_BYTES), "thumb.jpg", "image/jpeg")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    from flexlog.db.models import SessionLink
    link = db_session.query(SessionLink).first()
    assert link.thumbnail_media_id is not None


def test_traversal_filename_does_not_escape_uploads(client, db_session):
    """An uploader's malicious filename with .. doesn't escape uploads/."""
    from flexlog import paths
    p = _person(db_session)
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "../../escape.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    # The on-disk path is content-addressed, not filename-derived, so this
    # should always be inside uploads_dir.
    from flexlog.db.models import MediaFile
    mf = db_session.query(MediaFile).first()
    target = paths.resolve_file_key(mf.file_key)
    assert paths.uploads_dir().resolve() in target.resolve().parents
