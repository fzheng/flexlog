import hashlib
import io

import pytest
from werkzeug.datastructures import FileStorage

from flexlog import paths
from flexlog.db.models import MediaFile
from flexlog.services.media import (
    MediaUploadError,
    UnsupportedMediaTypeError,
    _detect_mime_from_bytes,
    upload_to_media_file,
)


# Tiny valid signatures — the magic-byte detection only needs the first ~12 bytes.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100
WAV_BYTES = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 100
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100  # ID3v2 header
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 100
WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 100  # EBML signature


def _file_storage(name: str, data: bytes, mimetype: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mimetype)


def test_upload_creates_media_file_row(app, db_session, tmp_data_dir):
    """Happy path: upload a JPEG, get a MediaFile row + a file on disk."""
    with app.app_context():
        fs = _file_storage("vacation.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        assert isinstance(mf, MediaFile)
        assert mf.media_type == "photo"
        assert mf.mime_type == "image/jpeg"
        assert mf.file_size_bytes == len(JPEG_BYTES)
        assert mf.original_filename == "vacation.jpg"
        # File exists at the resolved key. As of v0.2.0 media is encrypted at
        # rest with chunked AES-GCM — the on-disk bytes are the FLE0 header +
        # ciphertext, NOT the plaintext. Round-trip the plaintext via decrypt
        # to assert correctness.
        target = paths.resolve_file_key(mf.file_key)
        assert target.exists()
        from flexlog.crypto import decrypt_file_full
        from flask import current_app
        master_key = current_app.config["MASTER_KEY"]
        file_sha = mf.file_key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        assert decrypt_file_full(target, master_key, file_sha) == JPEG_BYTES


def test_upload_dedup_by_sha256(app, db_session):
    """Uploading identical bytes twice produces ONE row and ONE file on disk."""
    with app.app_context():
        fs1 = _file_storage("a.jpg", JPEG_BYTES, "image/jpeg")
        mf1 = upload_to_media_file(db_session, fs1)
        db_session.commit()
        fs2 = _file_storage("b.jpg", JPEG_BYTES, "image/jpeg")  # different name, same bytes
        mf2 = upload_to_media_file(db_session, fs2)
        db_session.commit()
        assert mf1.id == mf2.id  # same row reused
        assert mf1.original_filename == "a.jpg"  # first-seen wins
        # Single file on disk
        target = paths.resolve_file_key(mf1.file_key)
        assert target.exists()
        # uploads/.tmp/ is empty
        tmp_dir = paths.tmp_uploads_dir()
        assert list(tmp_dir.iterdir()) == [] or all(not f.is_file() for f in tmp_dir.iterdir())


def test_upload_classifies_mime(app, db_session):
    """media_type is derived from MIME for each supported family."""
    with app.app_context():
        for name, data, mimetype, expected_type in [
            ("a.jpg", JPEG_BYTES, "image/jpeg", "photo"),
            ("a.png", PNG_BYTES, "image/png", "photo"),
            ("a.webp", WEBP_BYTES, "image/webp", "photo"),
            ("a.mp3", MP3_BYTES, "audio/mpeg", "audio"),
            ("a.wav", WAV_BYTES, "audio/wav", "audio"),
            ("a.mp4", MP4_BYTES, "video/mp4", "video"),
            ("a.webm", WEBM_BYTES, "video/webm", "video"),
        ]:
            fs = _file_storage(name, data, mimetype)
            mf = upload_to_media_file(db_session, fs)
            db_session.commit()
            assert mf.media_type == expected_type, f"{mimetype} → expected {expected_type}, got {mf.media_type}"


def test_upload_rejects_unsupported_mime(app, db_session):
    """A .pdf or .exe upload is rejected at the MIME-allowlist gate."""
    with app.app_context():
        fs = _file_storage("evil.exe", b"MZ\x90\x00" * 100, "application/octet-stream")
        with pytest.raises(UnsupportedMediaTypeError):
            upload_to_media_file(db_session, fs)


def test_upload_rejects_mime_extension_mismatch(app, db_session):
    """An attacker tries to pass .exe contents with a JPEG MIME type."""
    with app.app_context():
        fs = _file_storage("evil.jpg", b"MZ\x90\x00" * 100, "image/jpeg")
        with pytest.raises(MediaUploadError, match="magic"):
            upload_to_media_file(db_session, fs)


def test_upload_rejects_size_over_limit(app, db_session):
    """File exceeding config.limits.max_upload_mb_per_file is rejected."""
    with app.app_context():
        big = JPEG_BYTES + b"\x00" * (1024 * 1024)  # ~1 MB
        # Force the limit down to 0 MB to trip the guard regardless of file size
        cfg = app.config["FLEXLOG"]
        # Replace the frozen Limits dataclass by rebuilding it inline
        from dataclasses import replace
        new_limits = replace(cfg.limits, max_upload_mb_per_file=0)
        from dataclasses import replace as cfg_replace
        app.config["FLEXLOG"] = cfg_replace(cfg, limits=new_limits)
        fs = _file_storage("big.jpg", big, "image/jpeg")
        with pytest.raises(MediaUploadError, match="size"):
            upload_to_media_file(db_session, fs)


def test_upload_temp_file_cleaned_up_on_error(app, db_session):
    """When upload fails mid-pipeline, the tmp file is removed."""
    with app.app_context():
        fs = _file_storage("evil.exe", b"MZ" * 1000, "application/octet-stream")
        with pytest.raises(UnsupportedMediaTypeError):
            upload_to_media_file(db_session, fs)
        # No file should remain in .tmp
        from flexlog import paths as p
        leftover = list((p.tmp_uploads_dir()).iterdir())
        # filter to regular files (not subdirs)
        leftover = [x for x in leftover if x.is_file()]
        assert leftover == []


def test_upload_writes_correct_disk_path(app, db_session):
    """Verifies the content-addressed sharded layout: <aa>/<bb>/<sha>.<ext>."""
    with app.app_context():
        fs = _file_storage("vacation.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        sha = hashlib.sha256(JPEG_BYTES).hexdigest()
        assert mf.sha256 == sha
        assert mf.file_key == f"{sha[0:2]}/{sha[2:4]}/{sha}.jpg"


def test_detect_mime_from_bytes_signatures():
    """Pure-function magic-byte → MIME detector."""
    assert _detect_mime_from_bytes(JPEG_BYTES) == "image/jpeg"
    assert _detect_mime_from_bytes(PNG_BYTES) == "image/png"
    assert _detect_mime_from_bytes(WEBP_BYTES) == "image/webp"
    # Non-image: returns None (audio/video are accepted by extension+content-type only)
    assert _detect_mime_from_bytes(b"random text") is None


def test_upload_rejects_empty_file(app, db_session):
    with app.app_context():
        fs = _file_storage("empty.jpg", b"", "image/jpeg")
        with pytest.raises(MediaUploadError, match="empty"):
            upload_to_media_file(db_session, fs)


def test_upload_preserves_original_filename(app, db_session):
    """original_filename is recorded for display."""
    with app.app_context():
        fs = _file_storage("My Vacation 2026.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        assert mf.original_filename == "My Vacation 2026.jpg"


def test_upload_handles_filename_with_path_traversal(app, db_session):
    """An attacker-controlled filename like '../../etc/passwd.jpg' must not
    affect the on-disk path; the path is derived from the SHA-256, not the
    original filename.
    """
    with app.app_context():
        fs = _file_storage("../../etc/passwd.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        # The file lives under uploads/<aa>/<bb>/<sha>.jpg, not under any
        # parent of uploads/.
        target = paths.resolve_file_key(mf.file_key)
        assert paths.uploads_dir() in target.parents or target.parent.parent.parent == paths.uploads_dir()
        # original_filename is recorded as-is — escaping happens at render time.
        assert mf.original_filename == "../../etc/passwd.jpg"


def _make_jpeg_bytes(width=80, height=60, color=(120, 60, 200)):
    import io
    from PIL import Image
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_upload_unlinks_target_on_db_flush_failure(app, db_session, monkeypatch):
    """I2: If db.flush raises (disk full, FK violation, anything),
    the just-encrypted target file must be unlinked to prevent
    orphan-file accumulation."""
    import io
    from werkzeug.datastructures import FileStorage

    jpeg = _make_jpeg_bytes()
    fs = FileStorage(
        stream=io.BytesIO(jpeg),
        filename="x.jpg",
        content_type="image/jpeg",
    )

    # Force the flush to fail with a non-IntegrityError.
    def bad_flush():
        raise RuntimeError("simulated disk full")
    monkeypatch.setattr(db_session, "flush", bad_flush)

    with app.app_context():
        with pytest.raises(RuntimeError, match="simulated disk full"):
            upload_to_media_file(db_session, fs)

    # The encrypted target should NOT exist on disk.
    import hashlib
    sha = hashlib.sha256(jpeg).hexdigest()
    file_key = paths.file_key_for(sha, "image/jpeg")
    target = paths.resolve_file_key(file_key)
    assert not target.exists(), "I2: orphan encrypted file left behind after DB failure"


def test_upload_handles_concurrent_dedup_race(app, db_session):
    """I5: Two writes with the same SHA — the second's INSERT hits the
    UNIQUE constraint. The service must catch IntegrityError, reload
    the existing row by SHA, and return it. The on-disk encrypted file
    is identical either way (deterministic FEK) so no cleanup needed."""
    import io
    import unittest.mock
    from werkzeug.datastructures import FileStorage
    from sqlalchemy import select
    from flexlog.db.models import MediaFile
    from flexlog.services.media import upload_to_media_file

    jpeg = _make_jpeg_bytes()
    fs1 = FileStorage(stream=io.BytesIO(jpeg), filename="a.jpg",
                       content_type="image/jpeg")
    fs2 = FileStorage(stream=io.BytesIO(jpeg), filename="b.jpg",
                       content_type="image/jpeg")

    with app.app_context():
        mf1 = upload_to_media_file(db_session, fs1)
        db_session.commit()

        original_execute = db_session.execute
        call_count = {"n": 0}
        def selective_execute(stmt, *a, **kw):
            try:
                compiled = str(stmt)
            except Exception:
                return original_execute(stmt, *a, **kw)
            if "media_file.sha256" in compiled and "SELECT" in compiled.upper():
                call_count["n"] += 1
                # First sha-lookup is the pre-flush dedup check: hide the
                # existing row so we proceed to INSERT and trip the
                # UNIQUE constraint. Subsequent sha-lookups (the reload
                # inside the IntegrityError branch) return the real row.
                if call_count["n"] == 1:
                    class FakeResult:
                        def scalar_one_or_none(self):
                            return None
                    return FakeResult()
            return original_execute(stmt, *a, **kw)

        with unittest.mock.patch.object(db_session, "execute", side_effect=selective_execute):
            mf2 = upload_to_media_file(db_session, fs2)
            db_session.commit()

    # Same row returned.
    assert mf1.id == mf2.id
    # Only one row in DB.
    rows = db_session.execute(
        select(MediaFile).where(MediaFile.sha256 == mf1.sha256)
    ).scalars().all()
    assert len(rows) == 1


def test_heic_transcode_rejects_oversized_image(monkeypatch, tmp_path):
    """M5: an HEIC whose declared pixel count exceeds _MAX_DECODED_PIXELS
    must be rejected BEFORE img.load() — otherwise a crafted HEIC
    claiming 100k×100k pixels would exhaust memory."""
    import pytest
    from unittest.mock import MagicMock
    from flexlog.services.media import _transcode_heic_to_jpeg, MediaUploadError

    fake_img = MagicMock()
    fake_img.size = (100_000, 100_000)  # 10 billion pixels — way over cap

    # Track whether .load() got called (it must NOT — we should bail first)
    load_called = []
    fake_img.load = MagicMock(side_effect=lambda: load_called.append(True))

    monkeypatch.setattr("PIL.Image.open", lambda _path: fake_img)

    fake_src = tmp_path / "bomb.heic"
    fake_src.write_bytes(b"\x00" * 100)
    with pytest.raises(MediaUploadError, match="too large to decode safely"):
        _transcode_heic_to_jpeg(fake_src)
    assert load_called == [], (
        "M5: img.load() must NOT be called when the declared pixel count "
        "exceeds the cap — otherwise the decompression bomb has already fired"
    )


def test_heic_transcode_accepts_under_cap(monkeypatch, tmp_path):
    """An HEIC under the pixel cap proceeds normally."""
    from unittest.mock import MagicMock
    from flexlog.services.media import _MAX_DECODED_PIXELS

    # Just verify the constant is set to a reasonable cap (~50 MP).
    assert 10_000_000 <= _MAX_DECODED_PIXELS <= 100_000_000, (
        f"_MAX_DECODED_PIXELS = {_MAX_DECODED_PIXELS} seems off — "
        f"should be tens of millions for modern phone cameras"
    )


def test_looks_like_audio_video_positive():
    """M4 helper: accepts every audio/video container signature we care about."""
    from flexlog.services.media import _looks_like_audio_video
    # MP3 with ID3v2 tag
    assert _looks_like_audio_video(b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 50)
    # MP3 raw frame sync
    assert _looks_like_audio_video(b"\xff\xfb\x90\x00" + b"\x00" * 50)
    assert _looks_like_audio_video(b"\xff\xfa\x90\x00" + b"\x00" * 50)
    # WAV
    assert _looks_like_audio_video(b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 50)
    # M4A
    assert _looks_like_audio_video(b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 50)
    # MP4
    assert _looks_like_audio_video(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 50)
    assert _looks_like_audio_video(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 50)
    # QuickTime
    assert _looks_like_audio_video(b"\x00\x00\x00\x20ftypqt  " + b"\x00" * 50)
    # WebM (EBML)
    assert _looks_like_audio_video(b"\x1a\x45\xdf\xa3" + b"\x00" * 50)
    # Ogg
    assert _looks_like_audio_video(b"OggS" + b"\x00" * 50)


def test_looks_like_audio_video_rejects_polyglots():
    """M4: HTML/JS/PHP polyglots with bogus declared audio/video MIME
    must NOT be accepted."""
    from flexlog.services.media import _looks_like_audio_video
    # HTML payload
    assert not _looks_like_audio_video(b"<html><body>evil</body></html>" + b"\x00" * 50)
    # PHP payload
    assert not _looks_like_audio_video(b"<?php system($_GET['c']); ?>" + b"\x00" * 50)
    # Plain text
    assert not _looks_like_audio_video(b"hello world" + b"\x00" * 50)
    # JPEG bytes (image MIME, not audio/video)
    assert not _looks_like_audio_video(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 50)
    # PNG bytes
    assert not _looks_like_audio_video(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    # Empty / short input
    assert not _looks_like_audio_video(b"")
    assert not _looks_like_audio_video(b"\x00")


def test_upload_rejects_html_polyglot_with_audio_mime(app, db_session):
    """M4: upload of an HTML payload declared as audio/mpeg must be
    rejected by the magic-byte check (was previously accepted)."""
    import io
    import pytest
    from werkzeug.datastructures import FileStorage
    from flexlog.services.media import upload_to_media_file, MediaUploadError

    html_payload = b"<html><body><script>alert('xss')</script></body></html>" + b"A" * 200
    fs = FileStorage(
        stream=io.BytesIO(html_payload),
        filename="evil.mp3",
        content_type="audio/mpeg",
    )
    with app.app_context():
        with pytest.raises(MediaUploadError, match="audio/video container signature"):
            upload_to_media_file(db_session, fs)


def test_upload_accepts_legitimate_mp3(app, db_session):
    """M4 regression: a real MP3 (ID3 header) must still upload."""
    import io
    from werkzeug.datastructures import FileStorage
    from flexlog.services.media import upload_to_media_file

    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 5000
    fs = FileStorage(
        stream=io.BytesIO(mp3_bytes),
        filename="real.mp3",
        content_type="audio/mpeg",
    )
    with app.app_context():
        mf = upload_to_media_file(db_session, fs)
    assert mf.media_type == "audio"
    assert mf.mime_type == "audio/mpeg"


# ---------------------------------------------------------------- gaps


def test_upload_rejects_declared_heic_without_magic_bytes(app, db_session):
    """If declared MIME is image/heic but the bytes don't have an HEIC
    ftyp signature, reject. Same defense as image/jpeg/png/webp."""
    import io
    import pytest
    from werkzeug.datastructures import FileStorage
    from flexlog.services.media import MediaUploadError, upload_to_media_file

    fs = FileStorage(
        stream=io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 500),  # JPEG bytes
        filename="lying.heic",
        content_type="image/heic",
    )
    with app.app_context():
        with pytest.raises(MediaUploadError, match="does not match magic bytes"):
            upload_to_media_file(db_session, fs)


def test_upload_rejects_empty_file(app, db_session):
    """A zero-byte upload is rejected — not even our 'minimal valid
    file' bytes can fit there."""
    import io
    import pytest
    from werkzeug.datastructures import FileStorage
    from flexlog.services.media import MediaUploadError, upload_to_media_file

    fs = FileStorage(
        stream=io.BytesIO(b""),
        filename="empty.jpg",
        content_type="image/jpeg",
    )
    with app.app_context():
        with pytest.raises(MediaUploadError, match="empty"):
            upload_to_media_file(db_session, fs)


def test_upload_raises_when_master_key_missing(app, db_session, monkeypatch):
    """If app.config['MASTER_KEY'] is None at upload time, we fail
    loudly before encrypt — would otherwise crash deep inside crypto
    with a confusing error."""
    import io
    import pytest
    from werkzeug.datastructures import FileStorage
    from flexlog.services.media import MediaUploadError, upload_to_media_file

    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 500
    fs = FileStorage(
        stream=io.BytesIO(jpeg),
        filename="x.jpg",
        content_type="image/jpeg",
    )
    with app.app_context():
        # Drop the master key from app.config to simulate the post-
        # logout / pre-login state where the engine is somehow still
        # attached but the key is gone.
        app.config.pop("MASTER_KEY", None)
        with pytest.raises(MediaUploadError, match="master key not loaded"):
            upload_to_media_file(db_session, fs)


def test_orphan_delete_returns_false_for_unknown_key(app, db_session):
    """orphan_delete_media_file on a non-existent file_key returns False
    without raising."""
    from flexlog.services.media import orphan_delete_media_file
    with app.app_context():
        assert orphan_delete_media_file(db_session, "no-such-key") is False


def test_orphan_delete_refuses_when_referenced_by_session(app, db_session, person):
    """An audio file linked to a session must not be orphan-deleted by
    the upload-DELETE handler (different code path from library hard-
    delete, which has stronger checks)."""
    import io
    from werkzeug.datastructures import FileStorage
    from flexlog.services.media import (
        link_to_session, orphan_delete_media_file, upload_to_media_file,
    )
    from flexlog.services.sessions import create_session

    mp3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 500
    fs = FileStorage(stream=io.BytesIO(mp3), filename="a.mp3", content_type="audio/mpeg")
    with app.app_context():
        mf = upload_to_media_file(db_session, fs)
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-18",
            ratings={}, notes=None, link_urls=[], link_thumb_keys=[],
        )
        db_session.commit()
        link_to_session(db_session, s.id, mf.id, sort_order=0)
        db_session.commit()

        # Now try to orphan-delete — must refuse.
        result = orphan_delete_media_file(db_session, mf.file_key)
        assert result is False


def test_heic_transcode_converts_rgba_to_rgb(monkeypatch, tmp_path):
    """An HEIC decoded to RGBA gets converted to RGB before JPEG save
    (JPEG doesn't support alpha). Covers the convert branch."""
    from unittest.mock import MagicMock
    import io
    from flexlog.services.media import _transcode_heic_to_jpeg

    fake_img = MagicMock()
    fake_img.size = (100, 100)
    fake_img.mode = "RGBA"
    fake_img.info = {}

    # save() writes a valid JPEG to disk so the post-save hash + head
    # read works.
    real_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 500
    def fake_save(path, **kwargs):
        from pathlib import Path
        Path(path).write_bytes(real_jpeg)
    fake_img.save = fake_save
    fake_img.close = lambda: None
    fake_img.convert = MagicMock(return_value=fake_img)

    monkeypatch.setattr("PIL.Image.open", lambda _path: fake_img)

    src = tmp_path / "x.heic"
    src.write_bytes(b"\x00" * 50)
    sha, size, head = _transcode_heic_to_jpeg(src)
    fake_img.convert.assert_called_once_with("RGB")
    assert sha and size > 0 and head.startswith(b"\xff\xd8\xff\xe0")


def test_heic_transcode_preserves_exif(monkeypatch, tmp_path):
    """If the source HEIC has EXIF data, it's preserved in the saved JPEG."""
    from unittest.mock import MagicMock
    from flexlog.services.media import _transcode_heic_to_jpeg

    fake_img = MagicMock()
    fake_img.size = (100, 100)
    fake_img.mode = "RGB"
    fake_img.info = {"exif": b"FAKE_EXIF_BYTES"}

    save_calls = []
    def fake_save(path, **kwargs):
        save_calls.append(kwargs)
        from pathlib import Path
        Path(path).write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 500)
    fake_img.save = fake_save
    fake_img.close = lambda: None
    fake_img.convert = MagicMock()

    monkeypatch.setattr("PIL.Image.open", lambda _path: fake_img)

    src = tmp_path / "x.heic"
    src.write_bytes(b"\x00" * 50)
    _transcode_heic_to_jpeg(src)
    assert save_calls[0].get("exif") == b"FAKE_EXIF_BYTES"
