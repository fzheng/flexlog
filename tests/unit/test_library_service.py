import io

import pytest
from werkzeug.datastructures import FileStorage

from flexlog import paths
from flexlog.db.models import MediaFile, Person, SessionLink
from flexlog.services.library import (
    MediaLibraryRow,
    get_references,
    hard_delete,
    list_library,
)
from flexlog.services.media import upload_to_media_file
from flexlog.services.people import create_person
from flexlog.services.sessions import create_session

JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100


def _upload(app, db_session, name, data, mimetype):
    fs = FileStorage(stream=io.BytesIO(data), filename=name, content_type=mimetype)
    with app.app_context():
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
    return mf


def test_list_library_empty(db_session):
    assert list_library(db_session) == []


def test_list_library_returns_all_media(app, db_session):
    a = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    b = _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    rows = list_library(db_session)
    assert len(rows) == 2
    ids = {r.media_file.id for r in rows}
    assert ids == {a.id, b.id}


def test_list_library_filter_by_type(app, db_session):
    _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    photos = list_library(db_session, media_type="photo")
    audios = list_library(db_session, media_type="audio")
    videos = list_library(db_session, media_type="video")
    assert {r.media_file.media_type for r in photos} == {"photo"}
    assert {r.media_file.media_type for r in audios} == {"audio"}
    assert videos == []


def test_orphan_filter_includes_only_unreferenced(app, db_session):
    """A file referenced by a session is not an orphan; one with no refs is."""
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    orphan_audio = _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    # link the photo to a session
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", ratings={"energy": 4}, notes=None, link_urls=[])
    db_session.commit()
    from flexlog.services.media import link_to_session
    link_to_session(db_session, s.id, photo.id, sort_order=0)
    db_session.commit()
    # orphan filter
    rows = list_library(db_session, orphans_only=True)
    ids = {r.media_file.id for r in rows}
    assert ids == {orphan_audio.id}


def test_get_references_counts_session_media(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s1 = create_session(db_session, person_id=p.id, session_date="2026-04-01", ratings={}, notes=None, link_urls=[])
    s2 = create_session(db_session, person_id=p.id, session_date="2026-05-01", ratings={}, notes=None, link_urls=[])
    db_session.commit()
    from flexlog.services.media import link_to_session
    link_to_session(db_session, s1.id, photo.id)
    link_to_session(db_session, s2.id, photo.id)
    db_session.commit()
    refs = get_references(db_session, photo.id)
    assert refs.session_media_count == 2
    assert refs.avatar_count == 0
    assert refs.link_thumbnail_count == 0
    assert refs.total == 2


def test_get_references_counts_avatar(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = Person(id="p1", alias="Alice", avatar_media_id=photo.id)
    db_session.add(p); db_session.commit()
    refs = get_references(db_session, photo.id)
    assert refs.avatar_count == 1
    assert refs.session_media_count == 0


def test_get_references_counts_link_thumbnail(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(
        db_session, person_id=p.id, session_date="2026-04-01",
        ratings={}, notes=None,
        link_urls=["https://example.com"],
    )
    db_session.commit()
    # set thumbnail manually
    s.links[0].thumbnail_media_id = photo.id
    db_session.commit()
    refs = get_references(db_session, photo.id)
    assert refs.link_thumbnail_count == 1


def test_hard_delete_removes_row_and_disk_file(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    target = paths.resolve_file_key(photo.file_key)
    assert target.exists()
    with app.app_context():
        hard_delete(db_session, photo.id)
        db_session.commit()
    # DB row gone
    assert db_session.get(MediaFile, photo.id) is None
    # Disk file gone
    assert not target.exists()


def test_hard_delete_cascades_session_media_and_nulls_avatar(app, db_session):
    """Hard-delete from Library: session_media joins go via cascade; avatar
    FK SET NULL.
    """
    from sqlalchemy import text

    from flexlog.services.media import link_to_session

    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    p.avatar_media_id = photo.id
    s = create_session(db_session, person_id=p.id, session_date="2026-04-01", ratings={}, notes=None, link_urls=[])
    db_session.commit()
    link_to_session(db_session, s.id, photo.id, sort_order=0)
    db_session.commit()

    assert db_session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 1
    with app.app_context():
        hard_delete(db_session, photo.id)
        db_session.commit()
    db_session.expire_all()
    assert db_session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 0
    refreshed_p = db_session.get(Person, p.id)
    assert refreshed_p.avatar_media_id is None


def test_hard_delete_missing_id_raises(app, db_session):
    from flexlog.services.library import MediaNotFoundError
    with app.app_context():
        with pytest.raises(MediaNotFoundError):
            hard_delete(db_session, "nope")


def test_list_library_orders_newest_first(app, db_session):
    a = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    b = _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    rows = list_library(db_session)
    # b uploaded after a, expect b first
    assert rows[0].media_file.id == b.id
    assert rows[1].media_file.id == a.id


def test_media_library_row_total_refs(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    rows = list_library(db_session)
    assert len(rows) == 1
    assert isinstance(rows[0], MediaLibraryRow)
    assert rows[0].total_refs == 0
    assert rows[0].is_orphan
