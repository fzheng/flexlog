"""Session CRUD + custom-rating split.

Sessions belong to a person and carry an overall_score (required, 0..5),
optional notes, optional custom-rating values (stored as a JSON object on
the row so the schema doesn't churn when the user adds/removes rating
dimensions in config.json), and zero or more SessionLinks (URL + optional
label; each link can also carry an optional thumbnail MediaFile reference).

split_custom_ratings() is the read-side helper: given the stored JSON and
the currently enabled rating IDs from config, it returns (current_pairs,
archived_pairs) for the template to render.
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


def _validate_inputs(person: Person | None, session_date: str, overall_score: int) -> None:
    if person is None:
        raise ValueError("person not found for the given person_id")
    if not isinstance(session_date, str) or not _DATE_RE.match(session_date):
        raise ValueError(f"session_date must be ISO YYYY-MM-DD, got {session_date!r}")
    if not isinstance(overall_score, int) or not (0 <= overall_score <= 5):
        raise ValueError(f"overall_score must be an integer 0..5, got {overall_score!r}")


def _serialize_ratings(custom_ratings: dict[str, int]) -> str:
    """Coerce the dict into a deterministic JSON string."""
    return json.dumps(dict(sorted(custom_ratings.items())))


def _replace_links(
    db: Session,
    session_row: SessionRow,
    links: list[dict],
    preserve_thumbnails: list[str | None] | None = None,
) -> None:
    """Drop existing links and recreate from `links` (rows with URL+label).

    Empty/whitespace URLs are silently dropped — accommodates form submission
    of empty rows from the link manager.

    `preserve_thumbnails` is an optional parallel list of thumbnail_media_id
    values to restore on the new links (after thumbnail-clear filtering is
    applied by the caller).
    """
    session_row.links = []
    new_link_index = 0
    for i, link in enumerate(links):
        url = (link.get("url") or "").strip()
        if not url:
            continue
        label = (link.get("label") or "").strip() or None
        thumb_id: str | None = None
        if preserve_thumbnails is not None and new_link_index < len(preserve_thumbnails):
            thumb_id = preserve_thumbnails[new_link_index]
        session_row.links.append(
            SessionLink(
                id=str(uuid.uuid4()),
                session_id=session_row.id,
                url=url,
                label=label,
                sort_order=i,
                thumbnail_media_id=thumb_id,
            )
        )
        new_link_index += 1


def create_session(
    db: Session,
    person_id: str,
    session_date: str,
    overall_score: int,
    custom_ratings: dict[str, int],
    notes: str | None,
    links: list[dict],
    media_uploads: list | None = None,
    link_thumbnails: list | None = None,
) -> SessionRow:
    """Create a Session row + its links. Caller commits."""
    person = db.get(Person, person_id)
    _validate_inputs(person, session_date, overall_score)

    session_row = SessionRow(
        id=str(uuid.uuid4()),
        person_id=person_id,
        session_date=session_date,
        overall_score=overall_score,
        custom_ratings_json=_serialize_ratings(custom_ratings),
        notes=(notes or None) if (notes is None or notes.strip() == "") else notes,
    )
    db.add(session_row)
    db.flush()
    _replace_links(db, session_row, links)

    if media_uploads:
        from flexlog.services.media import link_to_session, upload_to_media_file
        next_sort = 0
        for fs in media_uploads:
            if fs is None or fs.filename == "":
                continue
            mf = upload_to_media_file(db, fs)
            link_to_session(db, session_row.id, mf.id, sort_order=next_sort)
            next_sort += 1

    if link_thumbnails:
        from flexlog.services.media import upload_to_media_file
        for i, thumb_fs in enumerate(link_thumbnails):
            if thumb_fs is None or thumb_fs.filename == "":
                continue
            if i >= len(session_row.links):
                continue
            mf = upload_to_media_file(db, thumb_fs)
            session_row.links[i].thumbnail_media_id = mf.id

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
    overall_score: int,
    custom_ratings: dict[str, int],
    notes: str | None,
    links: list[dict],
    media_uploads: list | None = None,
    link_thumbnails: list | None = None,
    remove_session_media_ids: list[str] | None = None,
    clear_link_thumbnail_link_ids: list[str] | None = None,
) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    _validate_inputs(session_row.person, session_date, overall_score)
    session_row.session_date = session_date
    session_row.overall_score = overall_score
    session_row.custom_ratings_json = _serialize_ratings(custom_ratings)
    session_row.notes = notes if (notes and notes.strip()) else None

    # Capture thumbnail_media_ids from existing links (in URL order) before
    # _replace_links wipes them. Apply clear_link_thumbnail_link_ids filtering
    # so that cleared thumbs become None in the preserved list.
    clear_ids: set[str] = set(clear_link_thumbnail_link_ids or [])
    existing_thumbs: list[str | None] = []
    for existing_link in session_row.links:
        if existing_link.id in clear_ids:
            existing_thumbs.append(None)
        else:
            existing_thumbs.append(existing_link.thumbnail_media_id)

    _replace_links(db, session_row, links, preserve_thumbnails=existing_thumbs)

    if remove_session_media_ids:
        from flexlog.services.media import unlink_from_session
        for sm_id in remove_session_media_ids:
            unlink_from_session(db, sm_id)

    if media_uploads:
        from flexlog.services.media import link_to_session, upload_to_media_file
        existing_max = max((sm.sort_order for sm in session_row.media_joins), default=-1)
        next_sort = existing_max + 1
        for fs in media_uploads:
            if fs is None or fs.filename == "":
                continue
            mf = upload_to_media_file(db, fs)
            link_to_session(db, session_id, mf.id, sort_order=next_sort)
            next_sort += 1

    if link_thumbnails:
        from flexlog.services.media import upload_to_media_file
        for i, thumb_fs in enumerate(link_thumbnails):
            if thumb_fs is None or thumb_fs.filename == "":
                continue
            if i >= len(session_row.links):
                continue
            mf = upload_to_media_file(db, thumb_fs)
            session_row.links[i].thumbnail_media_id = mf.id

    return session_row


def delete_session(db: Session, session_id: str) -> None:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    db.delete(session_row)


def split_custom_ratings(
    stored_json: str | None,
    enabled_ids: list[str],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Split stored ratings into (current, archived) per spec §6.4.

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
