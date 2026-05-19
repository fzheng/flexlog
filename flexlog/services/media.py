"""Upload pipeline + content-addressed storage.

The pipeline streams the incoming FileStorage to a tmp file inside
$FLEXLOG_DATA_DIR/uploads/.tmp/, computes SHA-256 in chunks, validates
size + MIME, and then either deduplicates against an existing media_file
row (deleting the tmp) or atomically renames the tmp into the canonical
content-addressed location and inserts a fresh media_file row.

Magic-byte detection is implemented for images only (JPEG, PNG, WebP) per
spec §4.3 — audio and video are validated by content-type/extension match
since their formats are too varied for a small signature check.
"""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path

from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from flexlog import paths
from flexlog.db.models import MediaFile, SessionMedia
from flexlog.hashing import sha256_hex_stream

CHUNK = 1024 * 1024  # 1 MiB

# HEIC support: pillow-heif registers itself as a Pillow opener. If the
# system libheif isn't present, the import fails and HEIC uploads are
# rejected with a clear message rather than crashing the app.
try:
    import pillow_heif  # type: ignore[import-not-found]
    pillow_heif.register_heif_opener()
    _HEIC_SUPPORT = True
except Exception:  # pragma: no cover — only fires when libheif is missing
    _HEIC_SUPPORT = False


class MediaUploadError(RuntimeError):
    """Raised when an upload fails validation."""


class UnsupportedMediaTypeError(MediaUploadError):
    """Raised when MIME type is outside the allowlist."""


# MIME → media_type classification (matches paths._MIME_TO_EXT keys).
# image/heic + image/heif are accepted at upload time but always transcoded
# to JPEG for storage — browsers other than Safari can't render HEIC, and
# the iPhone-default format would otherwise be invisible from Chrome/Firefox.
_MIME_TO_TYPE: dict[str, str] = {
    "image/jpeg": "photo",
    "image/png": "photo",
    "image/webp": "photo",
    "image/heic": "photo",
    "image/heif": "photo",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/mp4": "audio",
    "audio/x-m4a": "audio",
    "video/mp4": "video",
    "video/webm": "video",
    "video/quicktime": "video",
}

# HEIC/HEIF brand codes inside an ISO Base Media File Format `ftyp` box.
# The brand sits at bytes 8..12 of the file (after the 4-byte box size and
# the 4-byte `ftyp` type tag).
_HEIC_BRANDS = frozenset({
    b"heic", b"heix", b"heim", b"heis",
    b"hevc", b"hevx", b"hevm", b"hevs",
    b"mif1", b"msf1",
})


def _detect_mime_from_bytes(head: bytes) -> str | None:
    """Match the first ~12 bytes against image signatures. Returns None if
    not a recognized image (audio/video aren't checked here).
    """
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if _looks_like_heic(head):
        return "image/heic"
    return None


def _looks_like_heic(head: bytes) -> bool:
    """ISO BMFF `ftyp` box with a known HEIC/HEIF brand at bytes 8..12."""
    if len(head) < 12:
        return False
    if head[4:8] != b"ftyp":
        return False
    return head[8:12] in _HEIC_BRANDS


_MAX_DECODED_PIXELS = 50_000_000  # ~50 MP cap. iPhone HEIC tops out
                                   # at ~48 MP (iPhone 14 Pro main camera);
                                   # leaves room for legitimate panoramas
                                   # while rejecting decompression bombs
                                   # that would otherwise need GBs of RAM.


def _transcode_heic_to_jpeg(src_path) -> tuple[str, int, bytes]:
    """Open an HEIC file at `src_path`, save a high-quality JPEG to a
    sibling tmp path, rewrite `src_path` to point at the JPEG bytes.

    Resolution-preserving: no resize, quality=95, subsampling=0 (4:4:4 — no
    chroma subsampling so fine red/orange detail and skin tones stay sharp),
    optimize=True. EXIF is preserved when present.

    Returns (sha256_hex, size_bytes, head_bytes_64) for the new JPEG so the
    caller can resume the dedup/encrypt pipeline without re-streaming.

    Decompression-bomb defense (M5 from pentest): check declared pixel
    dimensions BEFORE img.load() so a crafted HEIC claiming 100k×100k
    pixels can't exhaust memory at decode time.
    """
    import hashlib
    import io

    from PIL import Image

    img = Image.open(src_path)
    # Check pixel count from the parsed header BEFORE decoding. img.size
    # is available after Image.open without a full decode.
    declared_pixels = img.size[0] * img.size[1]
    if declared_pixels > _MAX_DECODED_PIXELS:
        img.close()
        raise MediaUploadError(
            f"HEIC image is too large to decode safely: "
            f"{img.size[0]}x{img.size[1]} = {declared_pixels:,} pixels "
            f"(cap is {_MAX_DECODED_PIXELS:,})"
        )
    # Force decode now while the file handle is still cheap; later operations
    # might lazy-decode and we'd lose track of errors here.
    img.load()
    exif_bytes = img.info.get("exif")

    # Write to a fresh tmp adjacent to the source, then replace.
    new_path = src_path.with_suffix(src_path.suffix + ".jpg")
    save_kwargs: dict = {
        "format": "JPEG",
        "quality": 95,
        "subsampling": 0,  # 4:4:4, no chroma downsampling
        "optimize": True,
    }
    if exif_bytes:
        save_kwargs["exif"] = exif_bytes

    # Some HEIC inputs decode to non-RGB modes (e.g. RGBA, P). JPEG only
    # supports RGB/L/CMYK; convert as needed.
    if img.mode not in ("RGB", "L", "CMYK"):
        img = img.convert("RGB")

    img.save(new_path, **save_kwargs)
    img.close()

    # Re-hash the JPEG bytes and capture a fresh head for the magic-byte check.
    h = hashlib.sha256()
    size = 0
    head_bytes = b""
    with new_path.open("rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            if not head_bytes:
                head_bytes = chunk[:64]
            size += len(chunk)
            h.update(chunk)

    # Replace the source tmp with the JPEG (caller continues to use src_path).
    try:
        src_path.unlink()
    except FileNotFoundError:
        pass
    new_path.replace(src_path)
    return h.hexdigest(), size, head_bytes


def upload_to_media_file(db: Session, fs: FileStorage) -> MediaFile:
    """Run an uploaded FileStorage through the pipeline → MediaFile row.

    Caller is responsible for committing. The MediaFile row is added to the
    session via add() but not committed; downstream code (e.g. linking the
    file to a session) typically commits after composing the full graph.

    On dedup, returns the existing row without modifying it.
    """
    declared_mime = fs.mimetype or ""
    if declared_mime not in _MIME_TO_TYPE:
        raise UnsupportedMediaTypeError(
            f"unsupported MIME type {declared_mime!r}; "
            f"allowed: {sorted(_MIME_TO_TYPE)}"
        )

    cfg = current_app.config["FLEXLOG"]
    max_bytes = cfg.limits.max_upload_mb_per_file * 1024 * 1024

    paths.ensure_layout()
    tmp_dir = paths.tmp_uploads_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_name = secrets.token_hex(16) + ".part"
    tmp_path = tmp_dir / tmp_name

    sha = ""
    size = 0
    head_bytes = b""

    try:
        with tmp_path.open("wb") as out:
            import hashlib
            h = hashlib.sha256()
            while True:
                chunk = fs.stream.read(CHUNK)
                if not chunk:
                    break
                if not head_bytes:
                    head_bytes = chunk[:64]  # capture the first chunk's head for magic-byte check
                size += len(chunk)
                if size > max_bytes:
                    raise MediaUploadError(
                        f"upload exceeds size cap of {cfg.limits.max_upload_mb_per_file} MiB"
                    )
                h.update(chunk)
                out.write(chunk)
            sha = h.hexdigest()

        if size == 0:
            raise MediaUploadError("upload is empty")

        # Image MIMEs: cross-check magic bytes
        if declared_mime in ("image/jpeg", "image/png", "image/webp"):
            detected = _detect_mime_from_bytes(head_bytes)
            if detected != declared_mime:
                raise MediaUploadError(
                    f"declared MIME {declared_mime!r} does not match magic bytes ({detected!r})"
                )

        # HEIC/HEIF: confirm magic bytes, then transcode to JPEG for storage
        # so non-Safari browsers can render the photo. The user's resolution
        # is preserved (no resize, quality=95, no chroma subsampling).
        if declared_mime in ("image/heic", "image/heif"):
            if not _looks_like_heic(head_bytes):
                raise MediaUploadError(
                    f"declared MIME {declared_mime!r} does not match magic bytes"
                )
            if not _HEIC_SUPPORT:
                raise UnsupportedMediaTypeError(
                    "HEIC upload received but pillow-heif / libheif is not "
                    "available on this server"
                )
            sha, size, head_bytes = _transcode_heic_to_jpeg(tmp_path)
            declared_mime = "image/jpeg"  # everything below is JPEG-shaped now

        media_type = _MIME_TO_TYPE[declared_mime]
        file_key = paths.file_key_for(sha, declared_mime)

        # Dedup: existing row?
        existing = db.execute(
            select(MediaFile).where(MediaFile.sha256 == sha)
        ).scalar_one_or_none()
        if existing is not None:
            # Drop the tmp; reuse the existing row.
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            return existing

        # New file: ensure target directory, encrypt tmp → target.
        master_key = current_app.config.get("MASTER_KEY")
        if master_key is None:
            raise MediaUploadError("master key not loaded; user must log in first")

        from flexlog.crypto import encrypt_file_to_path

        target = paths.resolve_file_key(file_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        encrypt_file_to_path(tmp_path, target, master_key, file_sha=sha)
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

        new_row = MediaFile(
            id=str(uuid.uuid4()),
            sha256=sha,
            file_key=file_key,
            media_type=media_type,
            original_filename=fs.filename,
            mime_type=declared_mime,
            file_size_bytes=size,
        )
        db.add(new_row)
        try:
            db.flush()
        except IntegrityError:
            # I5: concurrent upload of identical bytes won the race. The
            # encrypted file on disk is identical (deterministic FEK), so just
            # roll back our insert and reload the existing row.
            db.rollback()
            existing = db.execute(
                select(MediaFile).where(MediaFile.sha256 == sha)
            ).scalar_one_or_none()
            if existing is None:
                # Race-on-the-race: both writers somehow rolled back. SQLite's
                # write-serialization makes this practically impossible, but
                # defending here turns a NoResultFound 500 into a clear retryable
                # error.
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                raise MediaUploadError("upload dedup conflict; retry the upload")
            return existing
        except Exception:
            # I2: any other failure (disk full mid-flush, FK violation, etc.).
            # The encrypted file at `target` is ours alone — clean it up so
            # we don't leak an orphan.
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return new_row
    except Exception:
        # Best-effort cleanup of the tmp file (may already be gone).
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def link_to_session(
    db: Session, session_id: str, media_file_id: str, sort_order: int = 0
) -> SessionMedia:
    """Create the session_media join. Caller commits."""
    sm = SessionMedia(
        id=str(uuid.uuid4()),
        session_id=session_id,
        media_file_id=media_file_id,
        sort_order=sort_order,
    )
    db.add(sm)
    db.flush()
    return sm


def unlink_from_session(db: Session, session_media_id: str) -> None:
    """Soft-unlink: remove the session_media join. Media file persists."""
    sm = db.get(SessionMedia, session_media_id)
    if sm is not None:
        db.delete(sm)


def orphan_delete_media_file(db: Session, file_key: str) -> bool:
    """Best-effort orphan delete. If the MediaFile is referenced by any
    SessionMedia or Person.avatar_media_id, returns False without doing
    anything. Otherwise, deletes the encrypted file from disk + the row.

    Returns True iff the file was deleted."""
    from sqlalchemy import select
    from flexlog import paths
    from flexlog.db.models import MediaFile, Person, SessionMedia

    mf = db.execute(
        select(MediaFile).where(MediaFile.file_key == file_key)
    ).scalar_one_or_none()
    if mf is None:
        return False

    referenced_by_session = db.execute(
        select(SessionMedia.id).where(SessionMedia.media_file_id == mf.id).limit(1)
    ).scalar_one_or_none()
    referenced_as_avatar = db.execute(
        select(Person.id).where(Person.avatar_media_id == mf.id).limit(1)
    ).scalar_one_or_none()
    if referenced_by_session is not None or referenced_as_avatar is not None:
        return False

    target = paths.resolve_file_key(mf.file_key)
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(mf)
    db.flush()
    return True
