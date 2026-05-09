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


def test_detail_renders_audio_player(client, db_session):
    import io
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "audios": (io.BytesIO(MP3), "x.mp3", "audio/mpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import Session as SR
    sid = db_session.query(SR).first().id
    resp = client.get(f"/sessions/{sid}")
    body = resp.get_data(as_text=True)
    assert "<audio" in body
    assert "controls" in body


def test_detail_renders_photo_gallery(client, db_session):
    import io
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import Session as SR
    sid = db_session.query(SR).first().id
    resp = client.get(f"/sessions/{sid}")
    body = resp.get_data(as_text=True)
    assert "photo-grid" in body
    assert "data-pswp-width" in body
    assert "/media/" in body


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


def test_update_session_adds_new_photo(client, db_session):
    """Edit-and-add-photo: new media join created, sort_order continues from max+1."""
    from flexlog.db.models import MediaFile, Session as SR, SessionMedia
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
    JPEG2 = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x02" + b"\x00" * 100
    # Create with one photo
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "first.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    sess = db_session.query(SR).first()
    # Edit-add a second photo
    client.post(
        f"/sessions/{sess.id}",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG2), "second.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    db_session.expire_all()
    joins = db_session.query(SessionMedia).filter_by(session_id=sess.id).order_by(SessionMedia.sort_order).all()
    assert len(joins) == 2
    # Sort orders are 0 and 1 (or higher), strictly increasing
    assert joins[0].sort_order < joins[1].sort_order
    # Both media files exist
    assert db_session.query(MediaFile).count() == 2


def test_update_session_adds_link_thumbnail(client, db_session):
    """Edit and attach a thumbnail to the existing link."""
    from flexlog.db.models import Session as SR, SessionLink
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    # Create session with a link, no thumbnail
    client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15", "overall_score": "4",
            "link_url": ["https://example.com"],
            "link_label": ["Ref"],
        },
        content_type="multipart/form-data",
    )
    sess = db_session.query(SR).first()
    # Pre-edit: link has no thumbnail
    link = db_session.query(SessionLink).first()
    assert link.thumbnail_media_id is None

    # Edit and attach thumbnail
    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
    client.post(
        f"/sessions/{sess.id}",
        data={
            "session_date": "2026-04-15", "overall_score": "4",
            "link_url": ["https://example.com"],
            "link_label": ["Ref"],
            "link_thumbnail": (io.BytesIO(JPEG), "thumb.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    db_session.expire_all()
    refreshed = db_session.query(SessionLink).first()
    assert refreshed.thumbnail_media_id is not None


def test_update_session_clears_link_thumbnail(client, db_session):
    """clear_link_thumbnail[<link_id>] nulls the thumbnail FK."""
    from flexlog.db.models import Session as SR, SessionLink
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
    # Create session with a link AND thumbnail
    client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15", "overall_score": "4",
            "link_url": ["https://example.com"],
            "link_label": ["Ref"],
            "link_thumbnail": (io.BytesIO(JPEG), "thumb.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    sess = db_session.query(SR).first()
    link = db_session.query(SessionLink).first()
    assert link.thumbnail_media_id is not None
    link_id = link.id

    # Edit: clear the thumbnail. Re-submit the same link content with clear_link_thumbnail.
    client.post(
        f"/sessions/{sess.id}",
        data={
            "session_date": "2026-04-15", "overall_score": "4",
            "link_url": ["https://example.com"],
            "link_label": ["Ref"],
            "clear_link_thumbnail": [link_id],
        },
        content_type="multipart/form-data",
    )
    db_session.expire_all()
    # _replace_links creates new SessionLink rows with new UUIDs; query by session instead
    links_after = db_session.query(SessionLink).filter_by(session_id=sess.id).all()
    assert len(links_after) == 1
    assert links_after[0].thumbnail_media_id is None


def test_update_session_remove_session_media_via_route(client, db_session):
    """End-to-end: edit form posts remove_session_media[sm_id] → join dropped, file persists."""
    from flexlog.db.models import MediaFile, Session as SR, SessionMedia
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    sess = db_session.query(SR).first()
    sm = db_session.query(SessionMedia).first()
    sm_id = sm.id

    # Edit: remove the session_media row
    client.post(
        f"/sessions/{sess.id}",
        data={
            "session_date": "2026-04-15",
            "overall_score": "4",
            "remove_session_media": [sm_id],
        },
        content_type="multipart/form-data",
    )
    db_session.expire_all()
    assert db_session.query(SessionMedia).count() == 0
    assert db_session.query(MediaFile).count() == 1
