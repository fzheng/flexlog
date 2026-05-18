"""End-to-end: paste-screenshot link thumbnails.

Flow: user pastes a screenshot into a link row → JS uploads the image
via /sessions/upload (kind=photo) → returned file_key is stored in a
hidden `link_thumb_keys` input parallel to `link_urls` → on save, the
session service resolves the file_key to a MediaFile and sets
SessionLink.thumbnail_media_id.
"""
from __future__ import annotations

import io

from PIL import Image
from werkzeug.datastructures import FileStorage


def _make_jpeg_bytes(width=200, height=150, color=(40, 90, 160)):
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _upload_photo_get_key(db_session, color=(40, 90, 160)):
    """Push a JPEG through upload_to_media_file the same way the paste
    handler does (via the /sessions/upload route in production). Returns
    the resulting MediaFile so tests can use mf.file_key and mf.id."""
    from flexlog.services.media import upload_to_media_file
    fs = FileStorage(
        stream=io.BytesIO(_make_jpeg_bytes(color=color)),
        filename="pasted-screenshot.jpg",
        content_type="image/jpeg",
    )
    return upload_to_media_file(db_session, fs)


def test_create_session_with_thumb_key_sets_thumbnail_media_id(
    authed_client, person, db_session,
):
    from flexlog.services.sessions import create_session
    mf = _upload_photo_get_key(db_session)
    db_session.commit()

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[mf.file_key],
    )
    db_session.commit()

    assert len(s.links) == 1
    link = s.links[0]
    assert link.thumbnail_media_id == mf.id

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    assert "link-thumb-image" in body
    assert f"/media/{mf.file_key}" in body


def test_create_session_without_thumb_key_leaves_thumbnail_null(
    authed_client, person, db_session,
):
    from flexlog.services.sessions import create_session
    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 3}, notes=None,
        link_urls=["https://example.com/no-thumb"],
        link_thumb_keys=[""],
    )
    db_session.commit()

    assert len(s.links) == 1
    assert s.links[0].thumbnail_media_id is None

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    assert "https://example.com/no-thumb" in body
    assert "link-thumb-image" not in body


def test_create_session_with_unknown_key_silently_drops(
    authed_client, person, db_session,
):
    """A hand-crafted POST with a junk file_key shouldn't crash — the
    link just saves without a thumbnail."""
    from flexlog.services.sessions import create_session
    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=["nonexistent-file-key-xyz"],
    )
    db_session.commit()
    assert s.links[0].thumbnail_media_id is None


def test_create_session_with_audio_key_silently_drops(person, db_session):
    """Only photo MediaFiles are valid as link thumbnails. Pointing a
    link's thumb_key at an audio MediaFile (e.g. via a hand-crafted
    POST) should be ignored, not stored."""
    from flexlog.db.models import MediaFile
    from flexlog.services.sessions import create_session

    # Fabricate an audio MediaFile row directly (no upload pipeline
    # needed — we just want the file_key in the DB pointing at a
    # non-photo).
    audio = MediaFile(
        id="audio-mf-1",
        file_key="audio-key-1",
        media_type="audio",
        mime_type="audio/mpeg",
        file_size_bytes=1024,
        original_filename="x.mp3",
        sha256="0" * 64,
    )
    db_session.add(audio)
    db_session.flush()

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=["audio-key-1"],
    )
    db_session.commit()
    assert s.links[0].thumbnail_media_id is None


def test_update_session_can_replace_thumbnail(person, db_session):
    from flexlog.services.sessions import create_session, update_session
    mf_a = _upload_photo_get_key(db_session, color=(255, 0, 0))
    mf_b = _upload_photo_get_key(db_session, color=(0, 255, 0))
    db_session.commit()

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[mf_a.file_key],
    )
    db_session.commit()
    assert s.links[0].thumbnail_media_id == mf_a.id

    update_session(
        db_session, session_id=s.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[mf_b.file_key],
    )
    db_session.commit()
    assert s.links[0].thumbnail_media_id == mf_b.id


def test_update_session_can_clear_thumbnail(person, db_session):
    from flexlog.services.sessions import create_session, update_session
    mf = _upload_photo_get_key(db_session)
    db_session.commit()

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[mf.file_key],
    )
    db_session.commit()
    assert s.links[0].thumbnail_media_id == mf.id

    update_session(
        db_session, session_id=s.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[""],  # user cleared the thumbnail
    )
    db_session.commit()
    assert s.links[0].thumbnail_media_id is None


def test_update_session_preserves_thumbnail_when_key_resupplied(person, db_session):
    """The form always re-submits existing thumb_keys via their hidden
    inputs. Re-saving an unchanged session keeps the thumbnail."""
    from flexlog.services.sessions import create_session, update_session
    mf = _upload_photo_get_key(db_session)
    db_session.commit()

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[mf.file_key],
    )
    db_session.commit()

    update_session(
        db_session, session_id=s.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[mf.file_key],
    )
    db_session.commit()
    assert s.links[0].thumbnail_media_id == mf.id


def test_two_sessions_same_thumb_share_mediafile(person, db_session):
    """SHA-256 dedup in the media pipeline means two paste-uploads of
    the same image bytes resolve to the same MediaFile row."""
    from flexlog.services.sessions import create_session

    # Both uploads produce identical bytes → same SHA → same MediaFile.
    mf_a = _upload_photo_get_key(db_session)
    mf_b = _upload_photo_get_key(db_session)
    db_session.commit()
    assert mf_a.id == mf_b.id  # dedup

    s1 = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/a"],
        link_thumb_keys=[mf_a.file_key],
    )
    s2 = create_session(
        db_session, person_id=person.id, session_date="2026-05-18",
        ratings={"energy": 5}, notes=None,
        link_urls=["https://example.com/b"],
        link_thumb_keys=[mf_b.file_key],
    )
    db_session.commit()

    assert s1.links[0].thumbnail_media_id == s2.links[0].thumbnail_media_id


def test_edit_form_renders_existing_thumbnail(
    csrf_authed_client, csrf_person, csrf_db_session,
):
    """GET /sessions/<id>/edit renders the existing thumbnail's <img>
    + its hidden link_thumb_keys input pre-populated, so a re-save
    preserves the thumbnail without the user re-pasting."""
    from flexlog.services.sessions import create_session
    from flexlog.services.media import upload_to_media_file

    fs = FileStorage(
        stream=io.BytesIO(_make_jpeg_bytes()),
        filename="screenshot.jpg",
        content_type="image/jpeg",
    )
    mf = upload_to_media_file(csrf_db_session, fs)
    csrf_db_session.commit()

    s = create_session(
        csrf_db_session, person_id=csrf_person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[mf.file_key],
    )
    csrf_db_session.commit()

    body = csrf_authed_client.get(f"/sessions/{s.id}/edit").get_data(as_text=True)
    assert f"/media/{mf.file_key}" in body
    assert f'value="{mf.file_key}"' in body  # hidden link_thumb_keys input
    assert 'name="link_thumb_keys"' in body
