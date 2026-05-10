"""Person CRUD + dashboard search.

Tags travel with the person via `services.tags.normalize_tag_input` and
`services.tags.get_or_create_tag` so the route layer never touches Tag
directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from flexlog.db.models import Person, PersonTag, Session as SessionRow, Tag
from flexlog.services.tags import (
    get_or_create_tag,
    normalize_tag_input,
)


class PersonNotFoundError(LookupError):
    """Raised by update/delete when the target person id does not exist."""


def _validate_alias(alias: str) -> str:
    if not isinstance(alias, str) or alias.strip() == "":
        raise ValueError("alias is required and must not be empty or whitespace-only")
    return alias.strip()


def _apply_tags(session: Session, person: Person, tag_input: str) -> None:
    """Replace person.tags to match the parsed tag_input.

    Existing PersonTag rows for tags no longer present are removed; new ones
    are created. Tags themselves are never deleted.
    """
    desired_pairs = normalize_tag_input(tag_input)
    desired_slugs = {sl for _name, sl in desired_pairs}
    # Reassigning person.tags removes the corresponding person_tag rows but
    # does NOT delete Tag rows (Person.tags has no cascade — see models.py).
    # Drop joins for tags no longer desired
    person.tags = [t for t in person.tags if t.slug in desired_slugs]
    # Add joins for new tags (use get_or_create_tag to keep dedup)
    existing_slugs = {t.slug for t in person.tags}
    for display, sl in desired_pairs:
        if sl in existing_slugs:
            continue
        tag = get_or_create_tag(session, display)
        person.tags.append(tag)


_UNCHANGED = object()


def create_person(
    session: Session,
    alias: str,
    tag_input: str,
    avatar_media_id: str | None = None,
) -> Person:
    """Create a Person with the given alias, tag input, and optional avatar.

    Caller is responsible for committing. Raises ValueError if alias is empty.
    """
    person = Person(
        id=str(uuid.uuid4()),
        alias=_validate_alias(alias),
        avatar_media_id=avatar_media_id,
    )
    session.add(person)
    session.flush()
    _apply_tags(session, person, tag_input)
    return person


def get_person(session: Session, person_id: str) -> Person | None:
    """Return the Person with this id, or None if absent. Eager-loads tags."""
    stmt = select(Person).where(Person.id == person_id).options(selectinload(Person.tags))
    return session.execute(stmt).scalar_one_or_none()


def list_people(session: Session) -> list[Person]:
    """All people, alphabetical by alias (case-insensitive)."""
    stmt = (
        select(Person)
        .order_by(Person.alias.collate("NOCASE"))
        .options(selectinload(Person.tags))
    )
    return list(session.execute(stmt).scalars())


def search_people(session: Session, query: str) -> list[Person]:
    """Search people whose alias contains `query` OR who carry a tag whose
    name or slug contains `query`. Case-insensitive. Empty query → all.
    """
    q = (query or "").strip()
    if q == "":
        return list_people(session)
    like = f"%{q.lower()}%"
    stmt = (
        select(Person)
        .outerjoin(PersonTag, PersonTag.person_id == Person.id)
        .outerjoin(Tag, Tag.id == PersonTag.tag_id)
        .where(
            or_(
                Person.alias.ilike(like),
                Tag.name.ilike(like),
                Tag.slug.ilike(like),
            )
        )
        .order_by(Person.alias.collate("NOCASE"))
        .distinct()
        .options(selectinload(Person.tags))
    )
    return list(session.execute(stmt).scalars().unique())


def update_person(
    session: Session,
    person_id: str,
    alias: str,
    tag_input: str,
    avatar_media_id=_UNCHANGED,
) -> Person:
    """Update an existing person's alias and tags. Raises PersonNotFoundError.

    `avatar_media_id`:
      - omitted (sentinel): leave unchanged
      - None: clear the avatar
      - str: set to that media_file id
    """
    person = get_person(session, person_id)
    if person is None:
        raise PersonNotFoundError(person_id)
    person.alias = _validate_alias(alias)
    _apply_tags(session, person, tag_input)
    if avatar_media_id is not _UNCHANGED:
        person.avatar_media_id = avatar_media_id
    return person


def delete_person(session: Session, person_id: str) -> None:
    """Delete a person. Cascades through person_tag (FK) but leaves tags."""
    person = get_person(session, person_id)
    if person is None:
        raise PersonNotFoundError(person_id)
    session.delete(person)


@dataclass(frozen=True)
class DashboardRow:
    """One person's dashboard row with aggregates."""
    person: Person
    session_count: int
    last_session_date: str | None
    avg_overall_score: float | None


_VALID_SCALAR_SORTS = ("alias", "last_date", "session_count", "avg_score")


def list_dashboard_rows(
    session: Session,
    query: str,
    sort: str = "alias",
) -> list[DashboardRow]:
    """Return DashboardRows: one per person, with session aggregates.

    Search semantics match search_people: empty query → all; non-empty →
    case-insensitive substring match on alias OR tag.name OR tag.slug.

    Sort options:
      * "alias"          — alphabetical (default)
      * "last_date"      — last_session_date desc, NULLs last, alias asc tiebreak
      * "session_count"  — session_count desc, alias asc tiebreak
      * "avg_score"      — avg_overall_score desc, NULLs last, alias asc tiebreak
      * "custom:<dim_id>" — Python-side average of that dimension across the
                            person's sessions; NULLs last; alias asc tiebreak.

    Aggregates computed in a single grouped query with LEFT JOIN through
    session — people with no sessions still appear (zero/None aggregates).
    """
    q = (query or "").strip()
    base = (
        select(
            Person,
            func.count(SessionRow.id).label("session_count"),
            func.max(SessionRow.session_date).label("last_session_date"),
            func.avg(SessionRow.overall_score).label("avg_overall_score"),
        )
        .outerjoin(SessionRow, SessionRow.person_id == Person.id)
        .group_by(Person.id)
        .options(selectinload(Person.tags))
    )

    if q != "":
        like = f"%{q.lower()}%"
        # We need an EXISTS subquery here rather than another join: joining
        # through person_tag/tag would multiply rows before GROUP BY and
        # break aggregates (test_dashboard_rows_does_not_double_count_with_tags).
        tag_match = (
            select(PersonTag.person_id)
            .join(Tag, Tag.id == PersonTag.tag_id)
            .where(
                PersonTag.person_id == Person.id,
                or_(Tag.name.ilike(like), Tag.slug.ilike(like)),
            )
        )
        base = base.where(or_(Person.alias.ilike(like), exists(tag_match)))

    rows: list[DashboardRow] = []
    for person, count, last_date, avg_score in session.execute(base).all():
        rows.append(
            DashboardRow(
                person=person,
                session_count=int(count or 0),
                last_session_date=last_date,
                avg_overall_score=float(avg_score) if avg_score is not None else None,
            )
        )

    return _sort_rows(session, rows, sort)


def _sort_rows(
    session: Session, rows: list[DashboardRow], sort: str
) -> list[DashboardRow]:
    """Sort the dashboard rows by the requested column. Pure Python sort —
    fine at the bounded scale of the MVP (≤300 people).
    """
    alias_key = lambda r: r.person.alias.casefold()  # noqa: E731

    if sort == "alias" or (sort not in _VALID_SCALAR_SORTS and not sort.startswith("custom:")):
        return sorted(rows, key=alias_key)

    if sort == "last_date":
        return sorted(rows, key=lambda r: (r.last_session_date is None, _neg_str(r.last_session_date), alias_key(r)))

    if sort == "session_count":
        return sorted(rows, key=lambda r: (-r.session_count, alias_key(r)))

    if sort == "avg_score":
        return sorted(rows, key=lambda r: (r.avg_overall_score is None, -(r.avg_overall_score or 0.0), alias_key(r)))

    if sort.startswith("custom:"):
        dim_id = sort.split(":", 1)[1]
        avgs = _custom_dim_averages(session, dim_id)
        return sorted(
            rows,
            key=lambda r: (avgs.get(r.person.id) is None, -(avgs.get(r.person.id) or 0.0), alias_key(r)),
        )

    return sorted(rows, key=alias_key)


def _neg_str(s: str | None) -> str:
    """Sort strings descending by negating their lexical order using a chr(255)
    fill so that 'higher' ISO dates sort first when used as a positive key.
    """
    if s is None:
        return ""
    # Use complement: reverse-sort ISO date strings by inverting each char.
    return "".join(chr(255 - ord(c)) for c in s)


def _custom_dim_averages(session: Session, dim_id: str) -> dict[str, float]:
    """Return {person_id: avg_for_dim} across all sessions, ignoring sessions
    that don't carry that dimension. Pure Python — bounded at MVP scale.
    """
    import json
    rows = session.execute(
        select(SessionRow.person_id, SessionRow.custom_ratings_json)
    ).all()
    sums: dict[str, list[float]] = {}
    for person_id, raw in rows:
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        v = data.get(dim_id)
        if v is None:
            continue
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        sums.setdefault(person_id, []).append(num)
    return {pid: sum(vs) / len(vs) for pid, vs in sums.items() if vs}
