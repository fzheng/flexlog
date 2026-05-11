"""AJAX endpoints for the progressive session-form upload flow.

POST /sessions/upload  — multipart, returns JSON with the file_key
DELETE /sessions/upload/<file_key> — best-effort orphan delete

Both require auth (gated by the global before_request) and CSRF (the
Flask-WTF default reads X-CSRFToken from request headers).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from flexlog.db import get_db
from flexlog.services.media import (
    MediaUploadError,
    UnsupportedMediaTypeError,
    orphan_delete_media_file,
    upload_to_media_file,
)

upload_bp = Blueprint("upload", __name__)

_KIND_TO_MEDIA_TYPE = {"photo": "photo", "audio": "audio", "video": "video"}


@upload_bp.post("/sessions/upload")
def upload():
    kind = (request.form.get("kind") or "").strip()
    if kind not in _KIND_TO_MEDIA_TYPE:
        return jsonify({"error": f"unknown kind {kind!r}"}), 422

    fs = request.files.get("file")
    if fs is None or fs.filename == "":
        return jsonify({"error": "no file uploaded"}), 422

    db = get_db()
    try:
        mf = upload_to_media_file(db, fs)
    except UnsupportedMediaTypeError as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 415
    except MediaUploadError as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 413

    if mf.media_type != _KIND_TO_MEDIA_TYPE[kind]:
        db.rollback()
        return jsonify({
            "error": f"file is a {mf.media_type}, not a {kind}",
        }), 422

    db.commit()
    return jsonify({
        "file_key": mf.file_key,
        "original_filename": mf.original_filename,
        "media_type": mf.media_type,
        "size_bytes": mf.file_size_bytes,
        "mime": mf.mime_type,
    })


@upload_bp.delete("/sessions/upload/<path:file_key>")
def upload_delete(file_key: str):
    db = get_db()
    orphan_delete_media_file(db, file_key)
    db.commit()
    return "", 204
