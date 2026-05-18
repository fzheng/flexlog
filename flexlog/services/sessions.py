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

from flexlog.db.models import MediaFile, Person, Session as SessionRow, SessionLink

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
    thumb_keys: list[str],
) -> None:
    """Replace the session's links with the submitted URLs + thumbnails.

    `thumb_keys` is a parallel list to `urls`. Each entry is a
    MediaFile.file_key (set by the form-side paste handler after the
    user pasted a screenshot for that link), or "" for "no thumbnail".

    Unknown or non-photo keys silently drop to None — a defensive
    posture against a hand-crafted POST. The legitimate path always
    sees a freshly-uploaded photo file_key because the upload route
    only accepts kind=photo for paste-uploads."""
    if len(thumb_keys) < len(urls):
        thumb_keys = list(thumb_keys) + [""] * (len(urls) - len(thumb_keys))

    nonempty_keys = {(k or "").strip() for k in thumb_keys if (k or "").strip()}
    mf_by_key: dict[str, MediaFile] = {}
    if nonempty_keys:
        mf_by_key = {
            mf.file_key: mf
            for mf in db.execute(
                select(MediaFile).where(MediaFile.file_key.in_(nonempty_keys))
            ).scalars()
            if mf.media_type == "photo"
        }

    session_row.links = []
    for i, (raw_url, raw_key) in enumerate(zip(urls, thumb_keys)):
        url = (raw_url or "").strip()
        if not url:
            continue
        key = (raw_key or "").strip()
        mf = mf_by_key.get(key) if key else None
        session_row.links.append(
            SessionLink(
                id=str(uuid.uuid4()),
                session_id=session_row.id,
                url=url,
                label=None,
                sort_order=i,
                thumbnail_media_id=mf.id if mf is not None else None,
            )
        )


def create_session(
    db: Session,
    person_id: str,
    session_date: str,
    ratings: dict[str, int],
    notes: str | None,
    link_urls: list[str],
    link_thumb_keys: list[str] | None = None,
) -> SessionRow:
    """Create a Session row + its links. Caller commits.

    Media linking is handled separately via link_media_to_session — this
    function no longer accepts FileStorage uploads. Routes call the upload
    endpoint to encrypt+store, then call this with the file_keys.

    `link_thumb_keys` is a parallel list to `link_urls` of MediaFile
    file_keys (one per URL, or "" for none) — the paste-screenshot
    handler uploads each pasted image as a photo MediaFile and the form
    submits its file_key alongside the URL."""
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
    _replace_links(db, session_row, link_urls, link_thumb_keys or [])
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
    link_thumb_keys: list[str] | None = None,
) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    _validate_inputs(session_row.person, session_date)
    session_row.session_date = session_date
    session_row.ratings_json = _serialize_ratings(ratings)
    session_row.notes = notes if (notes and notes.strip()) else None

    _replace_links(db, session_row, link_urls, link_thumb_keys or [])
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


def compute_overall(
    stored_json: str | None,
    dims,
) -> float | None:
    """Weighted average of sub-rating values over enabled dimensions.

    Returns None when `stored_json` is empty/None/malformed, when no dims
    are enabled, or when the stored data is not a dict.

    Missing values are treated as 0. Values outside [0, 5] are clamped
    silently (defensive against hand-edited data).

    The denominator is implicitly 1.0 because validate_config_dict enforces
    that enabled-dim weights sum to 1.0.
    """
    if not stored_json:
        return None
    try:
        stored = json.loads(stored_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(stored, dict):
        return None
    enabled = [d for d in dims if d.enabled]
    if not enabled:
        return None
    total = 0.0
    for d in enabled:
        raw = stored.get(d.id, 0)
        if not isinstance(raw, int) or isinstance(raw, bool):
            v = 0
        else:
            v = raw
        if v < 0:
            v = 0
        elif v > 5:
            v = 5
        total += float(v) * d.weight
    return total


def link_media_to_session(
    db: Session, session_id: str, file_keys_by_kind: dict[str, list[str]]
) -> tuple[int, list[str]]:
    """Create SessionMedia join rows for each file_key. All-or-nothing on
    unknown keys: if any submitted key is unknown (e.g. orphan-deleted
    between upload and save) or kind-mismatched, NO joins are created and
    the unknown keys are returned for the caller to surface as a 422.

    Idempotent on already-linked pairs: if a (session_id, media_file_id)
    join already exists, the duplicate is silently skipped. The session
    edit form submits the FULL desired set of file_keys (both existing
    media's hidden inputs and newly-uploaded ones), so re-submitting
    existing media must not collide with the UNIQUE constraint on
    session_media(session_id, media_file_id).

    Returns (created_count, unknown_keys). Caller commits."""
    from flexlog.db.models import MediaFile, SessionMedia
    from sqlalchemy import select

    flat: list[tuple[str, str]] = [
        (kind, key)
        for kind in ("photo", "audio", "video")
        for key in file_keys_by_kind.get(kind, [])
    ]
    if not flat:
        return 0, []

    all_keys = [k for (_kind, k) in flat]
    mfs_by_key: dict[str, MediaFile] = {
        mf.file_key: mf
        for mf in db.execute(
            select(MediaFile).where(MediaFile.file_key.in_(all_keys))
        ).scalars()
    }
    unknown = [
        k for (kind, k) in flat
        if k not in mfs_by_key or mfs_by_key[k].media_type != kind
    ]
    if unknown:
        return 0, unknown

    # Existing (session_id, media_file_id) pairs — skip re-linking them.
    already_linked_mf_ids: set[str] = {
        row[0] for row in db.execute(
            select(SessionMedia.media_file_id).where(
                SessionMedia.session_id == session_id
            )
        ).all()
    }

    existing_max_stmt = select(SessionMedia.sort_order).where(
        SessionMedia.session_id == session_id
    )
    sort_order = max(
        (row[0] for row in db.execute(existing_max_stmt)), default=-1
    ) + 1

    created = 0
    for (_kind, key) in flat:
        mf = mfs_by_key[key]
        if mf.id in already_linked_mf_ids:
            continue
        db.add(SessionMedia(
            id=str(uuid.uuid4()),
            session_id=session_id,
            media_file_id=mf.id,
            sort_order=sort_order,
        ))
        already_linked_mf_ids.add(mf.id)  # guard against duplicates within `flat`
        sort_order += 1
        created += 1
    db.flush()
    return created, []


def unlink_media_from_session(
    db: Session, session_id: str, file_keys: list[str]
) -> int:
    """Remove SessionMedia rows by (session_id, file_key). Returns removed count."""
    from flexlog.db.models import MediaFile, SessionMedia
    from sqlalchemy import select, and_

    if not file_keys:
        return 0
    stmt = (
        select(SessionMedia)
        .join(MediaFile, MediaFile.id == SessionMedia.media_file_id)
        .where(and_(
            SessionMedia.session_id == session_id,
            MediaFile.file_key.in_(file_keys),
        ))
    )
    removed = 0
    for sm in db.execute(stmt).scalars():
        db.delete(sm)
        removed += 1
    return removed
