"""Friendly error handling when a media upload fails validation.

Before this fix, a too-big file (or any other MediaUploadError) bubbled
up as a 500 with a stack trace in the log. Now the route handlers catch
the error, flash the message, and re-render the form with prior text
data preserved (file inputs reset — browsers don't repopulate them).

Note: The two session-route upload error tests (session create/update)
were removed in Task 17 — their multipart-on-save path was removed in
M6 Task 5 and not restored. The equivalent coverage lives in
test_session_async_upload.py:test_upload_endpoint_rejects_bad_mime.
"""
from __future__ import annotations

import io
from unittest import mock

import pytest
from werkzeug.datastructures import FileStorage


from flexlog.services.media import MediaUploadError


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


# ---------------------------------------------------------------- upload_bp.py error branches


def test_upload_rejects_unknown_kind(authed_client):
    """POST /sessions/upload with kind=banana → 422 with clear error."""
    import io
    resp = authed_client.post(
        "/sessions/upload",
        data={
            "kind": "banana",
            "file": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 100), "x.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 422
    assert "unknown kind" in resp.get_data(as_text=True)


def test_upload_rejects_missing_file(authed_client):
    """POST /sessions/upload with no file → 422."""
    resp = authed_client.post(
        "/sessions/upload",
        data={"kind": "photo"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 422
    assert "no file" in resp.get_data(as_text=True).lower()


def test_upload_rejects_kind_mismatch(authed_client):
    """Upload a real JPEG declared as kind=audio → 422 with kind-mismatch
    message. The magic-byte check would have already failed for an
    audio MIME, so use a JPEG with kind=audio AND audio MIME: that
    fails earlier (magic byte). The kind-mismatch path triggers when
    upload succeeds (image MIME) but kind disagrees with media_type."""
    import io
    # A real JPEG with image/jpeg Content-Type but kind=audio.
    # upload_to_media_file accepts it as a photo; route then rejects.
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 500
    resp = authed_client.post(
        "/sessions/upload",
        data={
            "kind": "audio",
            "file": (io.BytesIO(jpeg), "x.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 422
    body = resp.get_data(as_text=True)
    assert "photo" in body and "audio" in body


def test_upload_rejects_oversize_with_413(authed_client, app):
    """A file larger than the per-kind cap → MediaUploadError → 413."""
    import io
    cfg = app.config["FLEXLOG"]
    over_cap_bytes = (cfg.limits.max_upload_mb_per_file + 1) * 1024 * 1024
    # 4 magic bytes + padding to exceed cap
    payload = b"\xff\xd8\xff\xe0" + b"\x00" * (over_cap_bytes - 4)
    resp = authed_client.post(
        "/sessions/upload",
        data={
            "kind": "photo",
            "file": (io.BytesIO(payload), "x.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413
    assert "size cap" in resp.get_data(as_text=True).lower()
