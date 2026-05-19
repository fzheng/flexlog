"""Media Library routes."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from flexlog.db import get_db
from flexlog.services.library import (
    MediaInUseError,
    MediaNotFoundError,
    hard_delete,
    list_library,
)
from flexlog.services.media import unlink_from_session

library_bp = Blueprint("library", __name__)


_VALID_TYPES = {"photo", "audio", "video"}


@library_bp.get("/library")
def index():
    media_type = request.args.get("type") or None
    if media_type not in _VALID_TYPES and media_type is not None:
        media_type = None
    orphans_only = request.args.get("orphans") == "1"
    rows = list_library(get_db(), media_type=media_type, orphans_only=orphans_only)
    return render_template(
        "library/index.html",
        rows=rows,
        active_type=media_type,
        orphans_only=orphans_only,
    )


@library_bp.post("/library/<media_file_id>/hard_delete")
def hard_delete_route(media_file_id: str):
    db = get_db()
    try:
        hard_delete(db, media_file_id)
    except MediaNotFoundError:
        abort(404)
    except MediaInUseError as exc:
        # Reference race: by the time the user clicked delete on what
        # the listing showed as an orphan, another tab added a reference.
        db.rollback()
        flash(
            "Cannot delete — this file is now referenced by a session, "
            "avatar, or link thumbnail. Remove those references first.",
            "error",
        )
        return redirect(url_for("library.index"))
    db.commit()
    flash("Deleted.", "success")
    return redirect(url_for("library.index"))


@library_bp.post("/sessions/<session_id>/media/<session_media_id>/unlink")
def unlink_from_session_route(session_id: str, session_media_id: str):
    """Soft-unlink: remove the session_media join. File stays on disk."""
    db = get_db()
    from flexlog.db.models import SessionMedia
    sm = db.get(SessionMedia, session_media_id)
    if sm is None or sm.session_id != session_id:
        abort(404)
    unlink_from_session(db, session_media_id)
    db.commit()
    return redirect(url_for("sessions.edit", session_id=session_id))
