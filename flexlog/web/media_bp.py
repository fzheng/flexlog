"""Sandboxed media file serving."""

from __future__ import annotations

from flask import Blueprint, abort, send_from_directory

from flexlog import paths
from flexlog.paths import FileKeyError

media_bp = Blueprint("media", __name__)


@media_bp.get("/media/<path:file_key>")
def serve(file_key: str):
    try:
        target = paths.resolve_file_key(file_key)
    except FileKeyError:
        abort(404)
    if not target.is_file():
        abort(404)
    # send_from_directory takes the directory + filename. We use the parent
    # of the resolved path to keep the sandbox tight.
    return send_from_directory(target.parent, target.name)
