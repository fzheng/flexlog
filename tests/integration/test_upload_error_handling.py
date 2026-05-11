"""Friendly error handling when a media upload fails validation.

Before this fix, a too-big file (or any other MediaUploadError) bubbled
up as a 500 with a stack trace in the log. Now the route handlers catch
the error, flash the message, and re-render the form with prior text
data preserved (file inputs reset — browsers don't repopulate them).
"""
from __future__ import annotations

import io
from unittest import mock

import pytest
from werkzeug.datastructures import FileStorage


from flexlog.services.media import MediaUploadError


# ----------------------------------------------------------- session create

@pytest.mark.skip(reason="Session-route media uploads removed in M6 Task 5; restored in Task 9.")
def test_session_create_renders_form_on_media_upload_error(
    authed_client, db_session, admin_password
):
    """Too-big file (or any MediaUploadError) during session create → 400
    with the form re-rendered and a flash message. NOT 500."""
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="UploadFail", tag_input="")
    db_session.commit()

    # Patch upload_to_media_file at the import site used by sessions.create_session
    with mock.patch(
        "flexlog.services.media.upload_to_media_file",
        side_effect=MediaUploadError("upload exceeds size cap of 500 MiB"),
    ):
        # Simulate a multipart POST with a "fake" attached photo. The
        # service-layer mock intercepts before any byte counts matter.
        fake_bytes = b"\xff\xd8\xff" + b"x" * 100
        resp = authed_client.post(
            f"/people/{p.id}/sessions",
            data={
                "session_date": "2026-05-10",
                "overall_score": 4,
                "notes": "These notes should survive the failed upload.",
                "photos": (io.BytesIO(fake_bytes), "huge.jpg"),
            },
            content_type="multipart/form-data",
        )

    assert resp.status_code == 400, "MediaUploadError must surface as 400, not 500"
    body = resp.get_data(as_text=True)
    assert "exceeds size cap" in body, "the flash message must reach the user"
    # Notes value is preserved in the re-rendered form
    assert "These notes should survive the failed upload." in body


@pytest.mark.skip(reason="Session-route media uploads removed in M6 Task 5; restored in Task 9.")
def test_session_update_renders_form_on_media_upload_error(
    authed_client, db_session, admin_password
):
    """Same protection on the update path."""
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias="UploadFail2", tag_input="")
    db_session.commit()
    s = create_session(
        db_session, person_id=p.id, session_date="2026-05-09",
        ratings={}, notes="original notes", link_urls=[],
    )
    db_session.commit()

    with mock.patch(
        "flexlog.services.media.upload_to_media_file",
        side_effect=MediaUploadError("upload exceeds size cap of 500 MiB"),
    ):
        fake_bytes = b"\xff\xd8\xff" + b"x" * 100
        resp = authed_client.post(
            f"/sessions/{s.id}",
            data={
                "session_date": "2026-05-10",
                "overall_score": 5,
                "notes": "updated notes that should survive",
                "photos": (io.BytesIO(fake_bytes), "huge.jpg"),
            },
            content_type="multipart/form-data",
        )

    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "exceeds size cap" in body
    assert "updated notes that should survive" in body


# ----------------------------------------------------------- person avatar

def test_person_create_renders_form_on_avatar_upload_error(authed_client):
    """Avatar dataURL bigger than the cap → 400 with flash + form re-render."""
    with mock.patch(
        "flexlog.web.people_bp.upload_to_media_file",
        side_effect=MediaUploadError("upload exceeds size cap of 500 MiB"),
    ):
        # A valid-looking JPEG dataURL prefix, doesn't matter what bytes;
        # the mock intercepts before disk write.
        import base64
        fake_blob = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 100).decode()
        resp = authed_client.post(
            "/people",
            data={
                "alias": "AvatarFail",
                "tags": "should-survive",
                "avatar_blob": fake_blob,
            },
        )

    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "Avatar upload failed" in body
    assert "exceeds size cap" in body
    # Alias and tags preserved in the re-rendered form
    assert "AvatarFail" in body
    assert "should-survive" in body


def test_person_update_renders_form_on_avatar_upload_error(authed_client, db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="AvatarFail2", tag_input="")
    db_session.commit()

    with mock.patch(
        "flexlog.web.people_bp.upload_to_media_file",
        side_effect=MediaUploadError("upload exceeds size cap of 500 MiB"),
    ):
        import base64
        fake_blob = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 100).decode()
        resp = authed_client.post(
            f"/people/{p.id}",
            data={
                "alias": "RenamedDuringFailedAvatar",
                "tags": "",
                "avatar_blob": fake_blob,
            },
        )

    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "Avatar upload failed" in body
    assert "exceeds size cap" in body
    # The form data the user typed is preserved
    assert "RenamedDuringFailedAvatar" in body
