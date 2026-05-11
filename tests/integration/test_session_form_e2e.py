"""End-to-end: upload via AJAX → submit the form referencing the file_keys
→ session lands with the right media joins + links."""
from __future__ import annotations

import io
import re

from tests.integration.test_session_async_upload import JPEG_1x1


def _csrf_token_from(client, path):
    body = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    return m.group(1)


def _upload(client, token, kind, fname, mime, content):
    resp = client.post(
        "/sessions/upload",
        data={"kind": kind, "file": (io.BytesIO(content), fname, mime)},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["file_key"]


def test_create_session_with_uploaded_media_and_links(csrf_authed_client, csrf_person):
    person = csrf_person
    token = _csrf_token_from(csrf_authed_client, f"/people/{person.id}/sessions/new")
    photo_key = _upload(csrf_authed_client, token, "photo", "p.jpg", "image/jpeg", JPEG_1x1)

    resp = csrf_authed_client.post(
        f"/people/{person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "2026-01-01",
            "rating_energy": "4",
            "notes": "hello",
            "photo_keys": [photo_key],
            "audio_keys": [],
            "video_keys": [],
            "link_urls": ["https://example.com/a"],
        },
    )
    # Should redirect to the detail page.
    assert resp.status_code == 302

    # Hit the detail page; verify the link + photo render.
    detail = csrf_authed_client.get(resp.headers["Location"])
    body = detail.get_data(as_text=True)
    assert "https://example.com/a" in body
    assert "rating_energy" not in body  # form field doesn't leak
    assert "Energy" in body  # rating label rendered


def test_create_session_rejects_stale_file_key_with_422(csrf_authed_client, csrf_person):
    """If the form posts a photo_keys[] referencing a file_key the server
    doesn't know (e.g. orphan-deleted between upload and Save), the route
    re-renders the form with a 422 and writes nothing to the DB."""
    person = csrf_person
    token = _csrf_token_from(csrf_authed_client, f"/people/{person.id}/sessions/new")

    resp = csrf_authed_client.post(
        f"/people/{person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "2026-01-01",
            "rating_energy": "4",
            "notes": "hello",
            "photo_keys": ["k/does-not-exist"],
        },
    )
    assert resp.status_code == 422
    body = resp.get_data(as_text=True)
    assert "stale key" in body.lower() or "no longer available" in body.lower()


def test_update_session_rejects_stale_file_key_with_422(csrf_authed_client, csrf_person, csrf_db_session):
    """Same guard on edit: a stale photo_keys[] entry rolls back the
    update and surfaces the error."""
    from flexlog.services.sessions import create_session
    person = csrf_person
    sess = create_session(
        csrf_db_session, person_id=person.id, session_date="2026-01-01",
        ratings={"energy": 3}, notes=None, link_urls=[],
    )
    csrf_db_session.commit()

    token = _csrf_token_from(csrf_authed_client, f"/sessions/{sess.id}/edit")
    resp = csrf_authed_client.post(
        f"/sessions/{sess.id}",
        data={
            "csrf_token": token,
            "session_date": "2026-01-02",
            "rating_energy": "5",
            "notes": "updated",
            "photo_keys": ["k/orphan-deleted"],
        },
    )
    assert resp.status_code == 422
    # The session's date should be unchanged because the txn rolled back.
    csrf_db_session.expire_all()
    from flexlog.services.sessions import get_session
    refetched = get_session(csrf_db_session, sess.id)
    assert refetched.session_date == "2026-01-01"
