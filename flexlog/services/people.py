"""Person CRUD + dashboard search.

Tags travel with the person via `services.tags.normalize_tag_input` and
`services.tags.get_or_create_tag` so the route layer never touches Tag
directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from flexlog.db.models import Person, PersonTag, Tag
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
    # Drop joins for tags no longer desired
    person.tags = [t for t in person.tags if t.slug in desired_slugs]
    # Add joins for new tags (use get_or_create_tag to keep dedup)
    existing_slugs = {t.slug for t in person.tags}
    for display, sl in desired_pairs:
        if sl in existing_slugs:
            continue
        tag = get_or_create_tag(session, display)
        person.tags.append(tag)


def create_person(session: Session, alias: str, tag_input: str) -> Person:
    """Create a Person with the given alias and comma-separated tag input.

    Caller is responsible for committing. Raises ValueError if alias is empty.
    """
    person = Person(id=str(uuid.uuid4()), alias=_validate_alias(alias))
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
    session: Session, person_id: str, alias: str, tag_input: str
) -> Person:
    """Update an existing person's alias and tags. Raises PersonNotFoundError."""
    person = get_person(session, person_id)
    if person is None:
        raise PersonNotFoundError(person_id)
    person.alias = _validate_alias(alias)
    _apply_tags(session, person, tag_input)
    return person


def delete_person(session: Session, person_id: str) -> None:
    """Delete a person. Cascades through person_tag (FK) but leaves tags."""
    person = get_person(session, person_id)
    if person is None:
        raise PersonNotFoundError(person_id)
    session.delete(person)
