"""POST /sessions/upload + DELETE /sessions/upload/<file_key>."""
from __future__ import annotations

import io

# A 1x1 JPEG (real JPEG bytes so magic-byte check passes).
JPEG_1x1 = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c14"
    "0d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27"
    "393d38323c2e333432ffdb0043010909090c0b0c180d0d1832211c213232323232323232323232"
    "32323232323232323232323232323232323232323232323232323232323232323232323232323232"
    "32ffc00011080001000103012200021101031101ffc4001f0000010501010101010100000000000000"
    "000102030405060708090a0bffc400b5100002010303020403050504040000017d010203000411051"
    "20613410761711322328114914223a153623e22458152732a2c2d2e2f23308293f1f25210ffc4001f"
    "0100030101010101010101010000000000000102030405060708090a0bffc400b5110002010204040"
    "30407050404000102770001020311043121052141061371229132061581914423a1b1c11425d1f02430"
    "626282939344d1f0f1ffda000c03010002110311003f00f7e8a28affd9"
)


def test_upload_endpoint_returns_file_key(csrf_authed_client):
    resp = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo", "file": (io.BytesIO(JPEG_1x1), "test.jpg", "image/jpeg")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": _csrf_token_from(csrf_authed_client)},
    )
    assert resp.status_code == 200
    j = resp.get_json()
    assert "file_key" in j
    assert j["media_type"] == "photo"
    assert j["mime"] == "image/jpeg"


def test_upload_endpoint_rejects_bad_mime(csrf_authed_client):
    resp = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo",
              "file": (io.BytesIO(b"hello"), "test.txt", "text/plain")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": _csrf_token_from(csrf_authed_client)},
    )
    assert resp.status_code == 415
    assert "error" in resp.get_json()


def test_upload_endpoint_rejects_without_csrf(csrf_authed_client):
    resp = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo",
              "file": (io.BytesIO(JPEG_1x1), "test.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code in (400, 403)  # CSRF rejection


def test_delete_endpoint_deletes_orphan(csrf_authed_client):
    token = _csrf_token_from(csrf_authed_client)
    up = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo", "file": (io.BytesIO(JPEG_1x1), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": token},
    )
    file_key = up.get_json()["file_key"]
    resp = csrf_authed_client.delete(
        f"/sessions/upload/{file_key}", headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 204


def _csrf_token_from(client):
    """Fetch a CSRF token by visiting any GET-rendered form."""
    resp = client.get("/people/new")
    body = resp.get_data(as_text=True)
    # The token lives in <input type="hidden" name="csrf_token" value="...">
    import re
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    if m is None:
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', body)
    assert m is not None, "no CSRF token in rendered form"
    return m.group(1)


def test_upload_endpoint_transcodes_heic_to_jpeg(csrf_authed_client):
    """An iPhone-style HEIC upload should be accepted and stored as a
    JPEG (so non-Safari browsers can render it). Resolution must be
    preserved."""
    from PIL import Image
    import pillow_heif  # noqa: F401 — opener registered by services.media import

    img = Image.new("RGB", (1280, 720), color=(40, 90, 160))
    buf = io.BytesIO()
    img.save(buf, format="HEIF", quality=90)
    heic_bytes = buf.getvalue()

    resp = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo",
              "file": (io.BytesIO(heic_bytes), "iphone.heic", "image/heic")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": _csrf_token_from(csrf_authed_client)},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    j = resp.get_json()
    assert j["media_type"] == "photo"
    # Transcoded — stored as JPEG, not HEIC.
    assert j["mime"] == "image/jpeg"
    # Filename preserved from the upload (so the user sees "iphone.heic"
    # in the Media Library even though the bytes on disk are JPEG).
    assert j["original_filename"] == "iphone.heic"
