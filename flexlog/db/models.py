"""SQLAlchemy ORM models for flexlog.

The full data model (PRD §7): Person + Tag + PersonTag (people side);
Session + SessionLink (per-person sessions with optional links); MediaFile
+ SessionMedia (uploaded photos / audio / video, with content-addressed
storage and dedup). Person.avatar_media_id and SessionLink.thumbnail_media_id
both reference MediaFile via ON DELETE SET NULL — hard-deleting a media
file from the Library leaves the references gracefully nulled rather than
cascading the parent rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flexlog.db import Base


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp string (default for created_at/updated_at)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class Person(Base):
    __tablename__ = "person"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    # FK to media_file with ON DELETE SET NULL — hard-deleting a MediaFile
    # from the Media Library clears the reference gracefully rather than
    # cascading the row that holds it.
    avatar_media_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("media_file.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_utcnow_iso, onupdate=_utcnow_iso
    )

    # NOTE: do NOT add cascade= here — tags are global per spec §6.10. The
    # services._apply_tags helper relies on the default secondary-relationship
    # semantics, which manage only the join rows on collection reassignment.
    # Adding cascade="all, delete-orphan" would make `person.tags = [...]`
    # hard-delete Tag rows. Keep tags cascade-free.
    tags: Mapped[List["Tag"]] = relationship(
        secondary="person_tag",
        back_populates="people",
        order_by="Tag.name",
    )

    avatar: Mapped["MediaFile | None"] = relationship(
        "MediaFile",
        foreign_keys=[avatar_media_id],
        lazy="joined",
    )

    sessions: Mapped[List["Session"]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        order_by="Session.session_date.desc()",
    )

    __table_args__ = (
        Index("ix_person_avatar_media", "avatar_media_id"),
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
# Session and media tables declare their own indexes inline (search by
# person_id, by session_date, by media_file_id, etc.).


class Session(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    person_id: Mapped[str] = mapped_column(
        String, ForeignKey("person.id", ondelete="CASCADE"), nullable=False
    )
    session_date: Mapped[str] = mapped_column(Text, nullable=False)  # YYYY-MM-DD
    ratings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_utcnow_iso, onupdate=_utcnow_iso
    )

    person: Mapped["Person"] = relationship(back_populates="sessions")
    links: Mapped[List["SessionLink"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionLink.sort_order",
    )
    media_joins: Mapped[List["SessionMedia"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionMedia.sort_order",
    )

    __table_args__ = (
        Index("ix_session_person_date", "person_id", "session_date"),
    )


class SessionLink(Base):
    __tablename__ = "session_link"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FK to media_file with ON DELETE SET NULL — hard-deleting a MediaFile
    # from the Media Library clears the link thumbnail reference gracefully.
    thumbnail_media_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("media_file.id", ondelete="SET NULL"),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)

    session: Mapped["Session"] = relationship(back_populates="links")

    __table_args__ = (
        Index("ix_session_link_thumbnail_media", "thumbnail_media_id"),
    )


class MediaFile(Base):
    __tablename__ = "media_file"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    file_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)  # 'photo' | 'audio' | 'video'
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)


class SessionMedia(Base):
    __tablename__ = "session_media"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    media_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("media_file.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)

    session: Mapped["Session"] = relationship(back_populates="media_joins")
    media_file: Mapped["MediaFile"] = relationship()

    __table_args__ = (
        UniqueConstraint("session_id", "media_file_id", name="uq_session_media_pair"),
        Index("ix_session_media_file", "media_file_id"),
    )
