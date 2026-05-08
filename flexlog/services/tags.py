"""Tag normalization, slugification, and ORM helpers.

Tags are global per the spec §6.1 and §7. Identity is the slug — different
display capitalizations collapse to a single tag. The slug is computed as:
  1. lowercased
  2. non-alphanumeric (Unicode-aware) → '-'
  3. consecutive '-' collapsed
  4. leading/trailing '-' stripped

Empty slugs are rejected. The display name remains as the user typed it
(first occurrence wins when reusing).
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from flexlog.db.models import Tag

_NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)
_UNDERSCORE_RE = re.compile(r"_+")
_DASH_RUN_RE = re.compile(r"-{2,}")


class InvalidTagError(ValueError):
    """Raised when a tag name slugifies to an empty string."""


def slugify(name: str) -> str:
    """Compute the canonical slug for a tag name.

    Raises InvalidTagError if the result is empty.
    """
    if not isinstance(name, str):
        raise InvalidTagError(f"tag name must be a string, got {type(name).__name__}")
    lowered = name.lower().strip()
    s = _NON_WORD_RE.sub("-", lowered)
    s = _UNDERSCORE_RE.sub("-", s)
    s = _DASH_RUN_RE.sub("-", s)
    s = s.strip("-")
    if not s:
        raise InvalidTagError(f"tag name {name!r} is empty after normalization")
    return s


def normalize_tag_input(raw: str) -> list[tuple[str, str]]:
    """Parse a comma-separated user input into [(display, slug), ...].

    Order: first appearance of each slug. Case-insensitive dedup. Tokens
    whose slug would be empty are dropped silently (so the user can type
    trailing commas without getting an error).
    """
    if not raw:
        return []
    seen_slugs: set[str] = set()
    out: list[tuple[str, str]] = []
    for raw_token in raw.split(","):
        display = raw_token.strip()
        if not display:
            continue
        try:
            sl = slugify(display)
        except InvalidTagError:
            continue
        if sl in seen_slugs:
            continue
        seen_slugs.add(sl)
        out.append((display, sl))
    return out


def get_or_create_tag(session: Session, name: str) -> Tag:
    """Return the Tag whose slug matches `name`, creating one if absent.

    Caller is responsible for `session.commit()`. Raises InvalidTagError
    if `name` slugifies to empty.
    """
    sl = slugify(name)
    existing = session.execute(select(Tag).where(Tag.slug == sl)).scalar_one_or_none()
    if existing is not None:
        return existing
    new_tag = Tag(id=str(uuid.uuid4()), name=name.strip(), slug=sl)
    session.add(new_tag)
    session.flush()
    return new_tag


def list_all_tags(session: Session) -> list[Tag]:
    """Return all tags in alphabetical-by-name order."""
    return list(session.execute(select(Tag).order_by(Tag.name)).scalars())
