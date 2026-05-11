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
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from flexlog import paths
from flexlog.db.models import MediaFile, SessionMedia
from flexlog.hashing import sha256_hex_stream

CHUNK = 1024 * 1024  # 1 MiB


class MediaUploadError(RuntimeError):
    """Raised when an upload fails validation."""


class UnsupportedMediaTypeError(MediaUploadError):
    """Raised when MIME type is outside the allowlist."""


# MIME → media_type classification (matches paths._MIME_TO_EXT keys)
_MIME_TO_TYPE: dict[str, str] = {
    "image/jpeg": "photo",
    "image/png": "photo",
    "image/webp": "photo",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/mp4": "audio",
    "audio/x-m4a": "audio",
    "video/mp4": "video",
    "video/webm": "video",
    "video/quicktime": "video",
}


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
    return None


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
        db.flush()
        return new_row
    except Exception:
        # Best-effort cleanup
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
