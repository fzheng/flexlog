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


# ---------- URL scheme safety gate ----------

def test_create_session_drops_javascript_url(person, db_session):
    """A hand-crafted POST with a javascript: URL must be silently dropped
    by the service-layer gate, never stored, never echoed back."""
    from flexlog.services.sessions import create_session
    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=["javascript:alert(1)", "https://example.com/ok"],
        link_thumb_keys=["", ""],
    )
    db_session.commit()
    assert len(s.links) == 1
    assert s.links[0].url == "https://example.com/ok"


def test_create_session_drops_data_and_file_urls(person, db_session):
    """Defense in depth — data: and file: URLs should also be rejected
    so that no non-http(s) scheme can ever land in storage."""
    from flexlog.services.sessions import create_session
    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes=None,
        link_urls=[
            "data:text/html,<script>x</script>",
            "file:///etc/passwd",
            "https://example.com/ok",
        ],
        link_thumb_keys=["", "", ""],
    )
    db_session.commit()
    assert [li.url for li in s.links] == ["https://example.com/ok"]


def test_is_safe_link_url_helper():
    """The helper is the single source of truth for the scheme gate."""
    from flexlog.services.sessions import is_safe_link_url
    assert is_safe_link_url("http://example.com")
    assert is_safe_link_url("https://example.com/path?q=1")
    assert is_safe_link_url("  https://example.com  ")  # whitespace OK
    assert not is_safe_link_url("javascript:alert(1)")
    assert not is_safe_link_url("JaVaScRiPt:alert(1)")  # case-insensitive
    assert not is_safe_link_url("data:text/html,<x>")
    assert not is_safe_link_url("file:///etc/passwd")
    assert not is_safe_link_url("//example.com")  # protocol-relative
    assert not is_safe_link_url("ftp://example.com")
    assert not is_safe_link_url("")
    assert not is_safe_link_url("   ")
    assert not is_safe_link_url(None)
    assert not is_safe_link_url(123)


# ---------- Route-level POST: full Flask stack with CSRF ----------

def _csrf_token_from(body: str) -> str:
    import re
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None, "csrf token not found in form body"
    return m.group(1)


def test_update_route_persists_link_thumb_key_via_form_post(
    csrf_authed_client, csrf_person, csrf_db_session,
):
    """End-to-end: POST /sessions/<id> with link_urls[] and parallel
    link_thumb_keys[] form fields. The route's
    _parse_link_thumb_keys_from_request → update_session pipeline must
    attach the thumb_key's MediaFile to the saved SessionLink."""
    from flexlog.services.media import upload_to_media_file
    from flexlog.services.sessions import create_session, get_session

    fs = FileStorage(
        stream=io.BytesIO(_make_jpeg_bytes()),
        filename="screenshot.jpg",
        content_type="image/jpeg",
    )
    mf = upload_to_media_file(csrf_db_session, fs)
    csrf_db_session.commit()

    # Seed a session with no thumbnail.
    s = create_session(
        csrf_db_session, person_id=csrf_person.id, session_date="2026-05-17",
        ratings={"energy": 3}, notes=None,
        link_urls=["https://example.com/article"],
        link_thumb_keys=[""],
    )
    csrf_db_session.commit()
    sid = s.id
    assert s.links[0].thumbnail_media_id is None

    # Scrape CSRF token from the edit form.
    edit_body = csrf_authed_client.get(f"/sessions/{sid}/edit").get_data(as_text=True)
    token = _csrf_token_from(edit_body)

    # POST through the real Flask handler, simulating the form submit
    # the JS would produce after a paste.
    resp = csrf_authed_client.post(
        f"/sessions/{sid}",
        data={
            "csrf_token": token,
            "session_date": "2026-05-17",
            "notes": "",
            "rating_energy": "3",
            "link_urls": ["https://example.com/article"],
            "link_thumb_keys": [mf.file_key],
        },
    )
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)[:500]

    # Re-fetch and confirm the thumbnail landed in the DB.
    s2 = get_session(csrf_db_session, sid)
    assert s2.links[0].thumbnail_media_id == mf.id


def test_update_route_drops_javascript_url_via_form_post(
    csrf_authed_client, csrf_person, csrf_db_session,
):
    """End-to-end: a javascript: URL submitted via the real POST handler
    must not land in the DB. Defense-in-depth — even if the client
    validator is bypassed, the server's is_safe_link_url gate catches it."""
    from flexlog.services.sessions import create_session, get_session

    s = create_session(
        csrf_db_session, person_id=csrf_person.id, session_date="2026-05-17",
        ratings={"energy": 3}, notes=None,
        link_urls=["https://example.com/safe"],
        link_thumb_keys=[""],
    )
    csrf_db_session.commit()
    sid = s.id

    edit_body = csrf_authed_client.get(f"/sessions/{sid}/edit").get_data(as_text=True)
    token = _csrf_token_from(edit_body)

    resp = csrf_authed_client.post(
        f"/sessions/{sid}",
        data={
            "csrf_token": token,
            "session_date": "2026-05-17",
            "notes": "",
            "rating_energy": "3",
            "link_urls": ["javascript:alert(1)", "https://example.com/safe"],
            "link_thumb_keys": ["", ""],
        },
    )
    assert resp.status_code in (302, 303)

    s2 = get_session(csrf_db_session, sid)
    assert [li.url for li in s2.links] == ["https://example.com/safe"]
