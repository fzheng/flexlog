"""Avatar upload end-to-end: dataURL → MediaFile row → person.avatar_media_id set.

Covers M5 avatar create / replace / clear flows. Replacement leaves the
previous MediaFile on disk (it becomes a Media Library orphan).
"""
from __future__ import annotations

import base64

from flexlog.db.models import MediaFile, Person
from flexlog.services.people import create_person


# 1x1 JPEG (smallest valid bytes that pass the magic-byte check)
_JPEG_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000302020203020203030303040303040504080605050505"
    "0a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514ffc0000b0801"
    "00010101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b51000020103"
    "030204030505040400000177000102031104052131410613516107227114328191a1b1c10923334252f0156272d10a162434"
    "e125f11718191a262728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a"
    "82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6"
    "d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbf3ffd9"
)


def _dataurl(raw: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def test_create_person_with_avatar_creates_media_file(client, db_session):
    resp = client.post(
        "/people",
        data={"alias": "Avi", "tags": "", "avatar_blob": _dataurl(_JPEG_BYTES)},
    )
    assert resp.status_code in (302, 303)
    db_session.expire_all()
    p = db_session.query(Person).filter_by(alias="Avi").one()
    assert p.avatar_media_id is not None
    mf = db_session.get(MediaFile, p.avatar_media_id)
    assert mf is not None
    assert mf.media_type == "photo"
    assert mf.mime_type == "image/jpeg"


def test_replace_avatar_leaves_old_media_file_orphaned(client, db_session):
    # Create with avatar A, then update to avatar B (same person).
    resp = client.post(
        "/people",
        data={"alias": "Bee", "tags": "", "avatar_blob": _dataurl(_JPEG_BYTES)},
    )
    assert resp.status_code in (302, 303)
    db_session.expire_all()
    p = db_session.query(Person).filter_by(alias="Bee").one()
    old_id = p.avatar_media_id
    assert old_id is not None

    # Distinct PNG bytes — minimal valid 1x1 PNG.
    png = (
        b"\x89PNG\r\n\x1a\n"  # signature
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"  # IHDR
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDAT\x78\x9c\x62\x00\x01\x00\x00\x05\x00\x01"
        b"\x0d\x0a\x2d\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = client.post(
        f"/people/{p.id}",
        data={"alias": "Bee", "tags": "", "avatar_blob": _dataurl(png, "image/png")},
    )
    assert resp.status_code in (302, 303)
    db_session.expire_all()
    p2 = db_session.get(Person, p.id)
    assert p2.avatar_media_id is not None
    assert p2.avatar_media_id != old_id
    # Old MediaFile still on disk
    old = db_session.get(MediaFile, old_id)
    assert old is not None


def test_clear_avatar_sets_avatar_media_id_null(client, db_session):
    resp = client.post(
        "/people",
        data={"alias": "Cee", "tags": "", "avatar_blob": _dataurl(_JPEG_BYTES)},
    )
    assert resp.status_code in (302, 303)
    db_session.expire_all()
    p = db_session.query(Person).filter_by(alias="Cee").one()
    assert p.avatar_media_id is not None

    resp = client.post(
        f"/people/{p.id}",
        data={"alias": "Cee", "tags": "", "clear_avatar": "y"},
    )
    assert resp.status_code in (302, 303)
    db_session.expire_all()
    p2 = db_session.get(Person, p.id)
    assert p2.avatar_media_id is None


def test_invalid_dataurl_rejected_silently(client, db_session):
    """Garbage in `avatar_blob` should be ignored (treated as 'no change'),
    not crash the request. Form-level length cap catches absurd inputs;
    parser fails closed for bogus prefixes.
    """
    resp = client.post(
        "/people",
        data={"alias": "Dee", "tags": "", "avatar_blob": "not-a-dataurl"},
    )
    assert resp.status_code in (302, 303)
    db_session.expire_all()
    p = db_session.query(Person).filter_by(alias="Dee").one()
    assert p.avatar_media_id is None
