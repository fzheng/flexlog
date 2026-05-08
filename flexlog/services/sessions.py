"""Session CRUD + custom-rating split.

Sessions belong to a person and carry an overall_score (required, 0..5),
optional notes, optional custom-rating values (stored as a JSON object on
the row so the schema doesn't churn when the user adds/removes rating
dimensions in config.json), and zero or more SessionLinks (URL + optional
label; thumbnails defer to M4).

split_custom_ratings() is the read-side helper: given the stored JSON and
the currently enabled rating IDs from config, it returns (current_pairs,
archived_pairs) for the template to render.
"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from flexlog.db.models import Person, Session as SessionRow, SessionLink

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def _replace_links(db: Session, session_row: SessionRow, links: list[dict]) -> None:
    """Drop existing links and recreate from `links` (rows with URL+label).

    Empty/whitespace URLs are silently dropped — accommodates form submission
    of empty rows from the link manager.
    """
    session_row.links = []
    for i, link in enumerate(links):
        url = (link.get("url") or "").strip()
        if not url:
            continue
        label = (link.get("label") or "").strip() or None
        session_row.links.append(
            SessionLink(
                id=str(uuid.uuid4()),
                session_id=session_row.id,
                url=url,
                label=label,
                sort_order=i,
            )
        )


def create_session(
    db: Session,
    person_id: str,
    session_date: str,
    overall_score: int,
    custom_ratings: dict[str, int],
    notes: str | None,
    links: list[dict],
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
) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    _validate_inputs(session_row.person, session_date, overall_score)
    session_row.session_date = session_date
    session_row.overall_score = overall_score
    session_row.custom_ratings_json = _serialize_ratings(custom_ratings)
    session_row.notes = notes if (notes and notes.strip()) else None
    _replace_links(db, session_row, links)
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
