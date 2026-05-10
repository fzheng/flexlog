"""On-disk media bytes are encrypted, not plaintext."""
from __future__ import annotations

import io
from werkzeug.datastructures import FileStorage


_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000302020203020203030303040303040504080605050505"
    "0a070706080c0a0c0c0b0a0b0b0d0e12100d0e110e0b0b1016101113141515150c0f171816141812141514ffc0000b08010001"
    "0101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b51000020103030204030"
    "505040400000177000102031104052131410613516107227114328191a1b1c10923334252f0156272d10a162434e125f1171819"
    "1a262728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788"
    "898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5"
    "e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbf3ffd9"
)


def test_uploaded_file_is_encrypted_on_disk(app, db_session):
    from flexlog.services.media import upload_to_media_file
    fs = FileStorage(stream=io.BytesIO(_JPEG), filename="test.jpg", content_type="image/jpeg")
    mf = upload_to_media_file(db_session, fs)
    db_session.commit()

    # Locate the file on disk
    from flexlog import paths
    on_disk = paths.resolve_file_key(mf.file_key)
    raw = on_disk.read_bytes()
    # Not the plaintext bytes
    assert raw[:3] != b"\xff\xd8\xff", "on-disk file should NOT start with JPEG magic"
    # Header has our magic
    assert raw[:4] == b"FLE0"


def test_dedup_works_under_encryption(app, db_session):
    """Uploading the same plaintext twice produces one media_file row and one
    on-disk file — the FEK + nonces are deterministic so ciphertext matches."""
    from flexlog.db.models import MediaFile
    from flexlog.services.media import upload_to_media_file

    fs1 = FileStorage(stream=io.BytesIO(_JPEG), filename="a.jpg", content_type="image/jpeg")
    mf1 = upload_to_media_file(db_session, fs1)
    db_session.commit()

    fs2 = FileStorage(stream=io.BytesIO(_JPEG), filename="b.jpg", content_type="image/jpeg")
    mf2 = upload_to_media_file(db_session, fs2)
    db_session.commit()

    assert mf1.id == mf2.id
    rows = db_session.query(MediaFile).all()
    assert len(rows) == 1
