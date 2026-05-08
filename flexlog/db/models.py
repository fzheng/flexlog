"""SQLAlchemy ORM models for flexlog.

M2 declares Person, Tag, PersonTag (the people side of the spec's data
model — §7). Sessions, links, media, and avatars come in M3/M4. The
`avatar_media_id` column is declared here as a plain nullable string so
M4 can layer the foreign-key constraint onto media_file without a schema
migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flexlog.db import Base


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp string (default for created_at/updated_at)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Person(Base):
    __tablename__ = "person"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    # FK to media_file lands in M4. For now, treat as a free string slot.
    avatar_media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_utcnow_iso, onupdate=_utcnow_iso
    )

    tags: Mapped[List["Tag"]] = relationship(
        secondary="person_tag",
        back_populates="people",
        order_by="Tag.name",
    )


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)

    people: Mapped[List[Person]] = relationship(
        secondary="person_tag",
        back_populates="tags",
    )


class PersonTag(Base):
    __tablename__ = "person_tag"

    person_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("person.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("tag.id", ondelete="CASCADE"),
        primary_key=True,
    )


# Lookup index on slug is already created by the unique constraint above.
# No further indexes in M2; M3 adds session(person_id, session_date).
