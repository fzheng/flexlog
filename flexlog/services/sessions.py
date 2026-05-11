"""Session CRUD + rating split.

Sessions belong to a person and carry optional notes, a unified
ratings dict (stored as JSON keyed by rating-dimension id, validated
against config at write time), and zero or more SessionLinks.

split_ratings() is the read-side helper: given the stored JSON and
the currently enabled rating IDs from config, it returns
(current_pairs, archived_pairs) for the template to render.
"""

from __future__ import annotations

import json
import re
import uuid

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from flexlog.db.models import Person, Session as SessionRow, SessionLink

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def enabled_rating_dimensions():
    """Return the list of enabled rating dimensions from app config."""
    cfg = current_app.config["FLEXLOG"]
    return [r for r in cfg.ratings if r.enabled]


class SessionNotFoundError(LookupError):
    """Raised by update/delete when the target session id does not exist."""


def _validate_inputs(person: Person | None, session_date: str) -> None:
    if person is None:
        raise ValueError("person not found for the given person_id")
    if not isinstance(session_date, str) or not _DATE_RE.match(session_date):
        raise ValueError(f"session_date must be ISO YYYY-MM-DD, got {session_date!r}")


def _serialize_ratings(ratings: dict[str, int]) -> str:
    """Deterministic JSON-string serialization of the ratings dict."""
    return json.dumps(dict(sorted(ratings.items())))


def _replace_links(
    db: Session,
    session_row: SessionRow,
    urls: list[str],
    preserve_thumbnails: list[str | None] | None = None,
) -> None:
    """Drop existing links and recreate from the URL list."""
    session_row.links = []
    new_link_index = 0
    for i, raw in enumerate(urls):
        url = (raw or "").strip()
        if not url:
            continue
        thumb_id: str | None = None
        if preserve_thumbnails is not None and new_link_index < len(preserve_thumbnails):
            thumb_id = preserve_thumbnails[new_link_index]
        session_row.links.append(
            SessionLink(
                id=str(uuid.uuid4()),
                session_id=session_row.id,
                url=url,
                label=None,
                sort_order=i,
                thumbnail_media_id=thumb_id,
            )
        )
        new_link_index += 1


def create_session(
    db: Session,
    person_id: str,
    session_date: str,
    ratings: dict[str, int],
    notes: str | None,
    link_urls: list[str],
) -> SessionRow:
    """Create a Session row + its links. Caller commits.

    Media linking is handled separately via link_media_to_session — this
    function no longer accepts FileStorage uploads. Routes call the upload
    endpoint to encrypt+store, then call this with the file_keys."""
    person = db.get(Person, person_id)
    _validate_inputs(person, session_date)

    session_row = SessionRow(
        id=str(uuid.uuid4()),
        person_id=person_id,
        session_date=session_date,
        ratings_json=_serialize_ratings(ratings),
        notes=(notes or None) if (notes is None or notes.strip() == "") else notes,
    )
    db.add(session_row)
    db.flush()
    _replace_links(db, session_row, link_urls)
    return session_row


def get_session(db: Session, session_id: str) -> SessionRow | None:
    stmt = (
        select(SessionRow)
        .where(SessionRow.id == session_id)
        .options(selectinload(SessionRow.links), selectinload(SessionRow.person))
    )
    return db.execute(stmt).scalar_one_or_none()


def list_sessions_for_person(db: Session, person_id: str) -> list[SessionRow]:
    """All sessions for `person_id`, newest first."""
    stmt = (
        select(SessionRow)
        .where(SessionRow.person_id == person_id)
        .order_by(SessionRow.session_date.desc())
        .options(selectinload(SessionRow.links))
    )
    return list(db.execute(stmt).scalars())


def update_session(
    db: Session,
    session_id: str,
    session_date: str,
    ratings: dict[str, int],
    notes: str | None,
    link_urls: list[str],
) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    _validate_inputs(session_row.person, session_date)
    session_row.session_date = session_date
    session_row.ratings_json = _serialize_ratings(ratings)
    session_row.notes = notes if (notes and notes.strip()) else None

    existing_thumbs: list[str | None] = [li.thumbnail_media_id for li in session_row.links]
    _replace_links(db, session_row, link_urls, preserve_thumbnails=existing_thumbs)
    return session_row


def delete_session(db: Session, session_id: str) -> None:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    db.delete(session_row)


def split_ratings(
    stored_json: str | None,
    enabled_ids: list[str],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Split stored ratings into (current, archived).

    `current` follows the order of `enabled_ids`; only IDs whose value is
    actually stored appear. `archived` is everything stored but absent
    from `enabled_ids`, in stored insertion order.
    """
    if not stored_json:
        return [], []
    try:
        stored = json.loads(stored_json)
    except (ValueError, TypeError):
        return [], []
    if not isinstance(stored, dict):
        return [], []
    enabled_set = set(enabled_ids)
    current: list[tuple[str, int]] = []
    for rid in enabled_ids:
        if rid in stored and isinstance(stored[rid], int):
            current.append((rid, stored[rid]))
    archived: list[tuple[str, int]] = []
    for rid, val in stored.items():
        if rid not in enabled_set and isinstance(val, int):
            archived.append((rid, val))
    return current, archived


# Backwards-compat alias used by older test files until they're updated.
split_custom_ratings = split_ratings
