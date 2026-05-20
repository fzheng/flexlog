"""Media Library queries: list with reference counts, orphan filter, hard delete.

Hard-delete is the ONLY route that removes a file from disk. Two stages:

  1. Inside the request transaction: re-check that the MediaFile has
     ZERO references (session_media, person.avatar, session_link.thumbnail);
     if any reference still exists, raise MediaInUseError and refuse.
     The check is duplicated here (`get_references`) even though the
     Library UI's orphan filter also runs it — the UI filter computes
     at list-time and can go stale by the moment the user POSTs the
     delete (another tab races a session save). Refusing prevents the
     pre-v0.8.0 silent-cascade behavior that quietly deleted joined
     references.
  2. After commit: a module-level `@event.listens_for(Session,
     "after_commit")` listener drains `session.info["pending_unlinks"]`
     and calls `paths.resolve_file_key(...).unlink(missing_ok=True)`.

DB commit FIRST, disk unlink SECOND. A failure between the two leaves an
orphaned file on disk (recoverable manually via the Library page) rather
than a dangling DB row pointing at a deleted file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from flexlog import paths
from flexlog.db.models import MediaFile, Person, SessionLink, SessionMedia

logger = logging.getLogger("flexlog.library")


# Module-level listener registered ONCE on the Session class (not on individual
# session instances). Fires on every commit; drains the per-session
# "pending_unlinks" set that hard_delete populates.
#
# I4: the previous pattern registered a NEW listener per hard_delete call, each
# capturing one file_key and guarded by a one-shot `fired` flag. That was
# fragile: a later unrelated db.commit() in the same request would fire all
# stale listeners and unlink files the second commit didn't intend to remove.
# A single class-level listener + per-session info dict collapses cleanly.
@event.listens_for(Session, "after_commit")
def _drain_pending_unlinks(session):
    pending = session.info.pop("pending_unlinks", None)
    if not pending:
        return
    # Import inside the listener to avoid a module-level circular-import
    # risk (storage may import db.models in future phases).
    from flexlog.storage import get_storage
    storage = get_storage()
    for file_key in pending:
        try:
            storage.delete(file_key)
        except Exception as exc:
            # M1: was silently swallowed; now logged so accumulated
            # phantom files are diagnosable in production. Continue
            # draining remaining keys rather than aborting the whole set.
            logger.warning(
                "failed to unlink %s after hard_delete commit: %s",
                file_key, exc,
            )


class MediaNotFoundError(LookupError):
    """Raised by hard_delete when the target media_file id does not exist."""


class MediaInUseError(RuntimeError):
    """Raised by hard_delete when the target media_file is still
    referenced (session_media join, person avatar, or link thumbnail).

    Without this check, a Library UI that filters by `is_orphan` could
    race a concurrent session save in another tab: the orphan flag is
    computed at list time and a new reference can be added between then
    and the hard-delete POST. The route handler should catch this and
    surface a clear "still in use" message rather than silently dropping
    refs via FK CASCADE/SET NULL."""


@dataclass(frozen=True)
class References:
    session_media_count: int
    avatar_count: int
    link_thumbnail_count: int

    @property
    def total(self) -> int:
        return self.session_media_count + self.avatar_count + self.link_thumbnail_count


@dataclass(frozen=True)
class MediaLibraryRow:
    media_file: MediaFile
    total_refs: int

    @property
    def is_orphan(self) -> bool:
        return self.total_refs == 0


def get_references(db: Session, media_file_id: str) -> References:
    """Count references across session_media, person.avatar_media_id,
    session_link.thumbnail_media_id.
    """
    sm = db.execute(
        select(func.count()).select_from(SessionMedia).where(SessionMedia.media_file_id == media_file_id)
    ).scalar_one()
    avatar = db.execute(
        select(func.count()).select_from(Person).where(Person.avatar_media_id == media_file_id)
    ).scalar_one()
    thumb = db.execute(
        select(func.count()).select_from(SessionLink).where(SessionLink.thumbnail_media_id == media_file_id)
    ).scalar_one()
    return References(
        session_media_count=int(sm),
        avatar_count=int(avatar),
        link_thumbnail_count=int(thumb),
    )


def list_library(
    db: Session,
    media_type: str | None = None,
    orphans_only: bool = False,
) -> list[MediaLibraryRow]:
    """List MediaLibraryRows (newest first), optionally filtered."""
    stmt = select(MediaFile).order_by(MediaFile.created_at.desc())
    if media_type is not None:
        stmt = stmt.where(MediaFile.media_type == media_type)
    files = list(db.execute(stmt).scalars())

    out: list[MediaLibraryRow] = []
    for mf in files:
        refs = get_references(db, mf.id)
        if orphans_only and refs.total > 0:
            continue
        out.append(MediaLibraryRow(media_file=mf, total_refs=refs.total))
    return out


def hard_delete(db: Session, media_file_id: str) -> None:
    """Hard-delete a media file: cascade joins, null out FKs, drop row, unlink disk file.

    Refuses (raises MediaInUseError) if any session_media join, person
    avatar, or link thumbnail still references the file. The Library UI's
    `is_orphan` filter is computed at list-time and can be stale by the
    moment the user POSTs the delete — re-check here, inside the same
    transaction, before destroying data.

    Caller is responsible for `db.commit()` after the call. The disk
    unlink happens in the module-level `_drain_pending_unlinks` listener
    that fires on every after_commit — so a partial failure between
    db.flush() and db.commit() never leaves a dangling DB row pointing
    at a deleted file.
    """
    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise MediaNotFoundError(media_file_id)
    refs = get_references(db, mf.id)
    if refs.total > 0:
        raise MediaInUseError(
            f"media_file {media_file_id} still has {refs.total} reference(s): "
            f"sessions={refs.session_media_count}, "
            f"avatars={refs.avatar_count}, "
            f"link_thumbnails={refs.link_thumbnail_count}"
        )
    file_key = mf.file_key
    db.delete(mf)
    db.flush()
    # Defer the disk unlink to after-commit. The module-level
    # _drain_pending_unlinks listener drains this set on every commit.
    # Using a set means duplicate calls within one transaction collapse
    # cleanly (idempotent). The listener is registered ONCE on SASession
    # (the class), so there is no per-call listener accumulation.
    db.info.setdefault("pending_unlinks", set()).add(file_key)
