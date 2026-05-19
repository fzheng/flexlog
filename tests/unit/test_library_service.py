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


def test_hard_delete_refuses_when_referenced(app, db_session):
    """Hard-delete from Library now REFUSES on any non-zero reference
    count (session_media, avatar, or link thumbnail). The previous
    behavior silently cascaded — that meant the user could "delete an
    orphan" and accidentally nuke their session's media link if the
    orphan-flag had gone stale between list-time and POST. Refusing
    forces them to unlink the references first."""
    from sqlalchemy import text

    from flexlog.services.library import MediaInUseError
    from flexlog.services.media import link_to_session

    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    p.avatar_media_id = photo.id
    s = create_session(
        db_session, person_id=p.id, session_date="2026-04-01",
        ratings={}, notes=None, link_urls=[],
    )
    db_session.commit()
    link_to_session(db_session, s.id, photo.id, sort_order=0)
    db_session.commit()

    assert db_session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 1
    with app.app_context():
        with pytest.raises(MediaInUseError):
            hard_delete(db_session, photo.id)
    db_session.rollback()

    # Crucially: nothing was deleted. Photo, session_media, and avatar
    # link all survive.
    db_session.expire_all()
    assert db_session.get(MediaFile, photo.id) is not None
    assert db_session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 1
    assert db_session.get(Person, p.id).avatar_media_id == photo.id


def test_hard_delete_succeeds_after_references_removed(app, db_session):
    """Once all references are dropped, hard_delete proceeds. This is
    the canonical workflow the UI guides the user through."""
    from sqlalchemy import text

    from flexlog.services.media import link_to_session

    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    p.avatar_media_id = photo.id
    s = create_session(
        db_session, person_id=p.id, session_date="2026-04-01",
        ratings={}, notes=None, link_urls=[],
    )
    db_session.commit()
    link_to_session(db_session, s.id, photo.id, sort_order=0)
    db_session.commit()

    # Strip references first.
    db_session.execute(text("DELETE FROM session_media WHERE media_file_id = :i"), {"i": photo.id})
    p.avatar_media_id = None
    db_session.commit()

    with app.app_context():
        hard_delete(db_session, photo.id)
        db_session.commit()

    assert db_session.get(MediaFile, photo.id) is None


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


def test_hard_delete_drains_multiple_pending_unlinks(app, db_session):
    """I4: hard_delete'ing N files in one transaction should fire ONE
    listener that drains all N file_keys on commit, not N listeners
    each capturing one file_key. Verified by: 3 orphan files, 3 calls,
    one commit, all 3 disk files unlinked."""
    from flexlog import paths
    from flexlog.db.models import MediaFile

    # Three different SHAs via different tail bytes — JPEG_BYTES at
    # module top already has valid magic-byte prefix; the rest is
    # arbitrary.
    photo1 = _upload(app, db_session, "1.jpg", JPEG_BYTES + b"\xaa", "image/jpeg")
    photo2 = _upload(app, db_session, "2.jpg", JPEG_BYTES + b"\xbb", "image/jpeg")
    photo3 = _upload(app, db_session, "3.jpg", JPEG_BYTES + b"\xcc", "image/jpeg")
    db_session.commit()

    targets = [paths.resolve_file_key(p.file_key) for p in (photo1, photo2, photo3)]
    for t in targets:
        assert t.exists()

    with app.app_context():
        hard_delete(db_session, photo1.id)
        hard_delete(db_session, photo2.id)
        hard_delete(db_session, photo3.id)
        db_session.commit()

    # All three on-disk files gone.
    for t in targets:
        assert not t.exists(), f"{t} should have been unlinked"
    # All three DB rows gone.
    for p in (photo1, photo2, photo3):
        assert db_session.get(MediaFile, p.id) is None


def test_hard_delete_logs_warning_on_unlink_failure(
    app, db_session, monkeypatch, caplog,
):
    """M1: a disk-unlink failure must be logged (was silently swallowed
    before). Without logging, accumulated phantom files are
    undiagnosable."""
    import logging
    from flexlog import paths
    from pathlib import Path

    photo = _upload(app, db_session, "x.jpg", JPEG_BYTES, "image/jpeg")
    db_session.commit()

    # Force unlink to fail.
    original_unlink = Path.unlink
    def bad_unlink(self, *a, **kw):
        if self.name.endswith(".jpg") or "uploads" in str(self):
            raise PermissionError("simulated permission denied")
        return original_unlink(self, *a, **kw)
    monkeypatch.setattr(Path, "unlink", bad_unlink)

    with app.app_context(), caplog.at_level(logging.WARNING, logger="flexlog"):
        hard_delete(db_session, photo.id)
        db_session.commit()

    # The DB row is gone (commit succeeded). The disk unlink failed and
    # was logged.
    assert any(
        "failed to unlink" in r.message.lower() for r in caplog.records
    ), f"expected unlink-failure warning, got: {[r.message for r in caplog.records]}"
