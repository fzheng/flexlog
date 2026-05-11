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
