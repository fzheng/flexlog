"""link_media_to_session / unlink_media_from_session create and remove
SessionMedia join rows. orphan_delete_media_file removes a MediaFile +
its on-disk encrypted blob only if nothing references it."""
from __future__ import annotations


def _create_media_file(db, kind, sha):
    import uuid
    from flexlog.db.models import MediaFile
    mf = MediaFile(
        id=str(uuid.uuid4()), sha256=sha, file_key=f"k/{sha}",
        media_type=kind, original_filename="f.bin", mime_type="image/jpeg",
        file_size_bytes=10,
    )
    db.add(mf)
    db.flush()
    return mf


def _create_session(db, person_id):
    from flexlog.services.sessions import create_session
    return create_session(
        db, person_id=person_id, session_date="2026-01-01",
        ratings={}, notes=None, link_urls=[],
    )


def test_link_media_to_session_creates_join_rows(db_session, person):
    from flexlog.services.sessions import link_media_to_session
    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "a" * 64)
    p2 = _create_media_file(db_session, "photo", "b" * 64)
    aud = _create_media_file(db_session, "audio", "c" * 64)

    link_media_to_session(db_session, s.id, {
        "photo": [p1.file_key, p2.file_key],
        "audio": [aud.file_key],
        "video": [],
    })
    db_session.commit()

    assert len(s.media_joins) == 3
    kinds = sorted(j.media_file.media_type for j in s.media_joins)
    assert kinds == ["audio", "photo", "photo"]


def test_link_ignores_unknown_file_keys(db_session, person):
    from flexlog.services.sessions import link_media_to_session
    s = _create_session(db_session, person.id)
    link_media_to_session(db_session, s.id, {
        "photo": ["k/does-not-exist"], "audio": [], "video": [],
    })
    db_session.commit()
    assert s.media_joins == []


def test_unlink_media_removes_join_rows(db_session, person):
    from flexlog.services.sessions import link_media_to_session, unlink_media_from_session
    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "d" * 64)
    p2 = _create_media_file(db_session, "photo", "e" * 64)
    link_media_to_session(db_session, s.id, {"photo": [p1.file_key, p2.file_key],
                                              "audio": [], "video": []})
    db_session.commit()

    unlink_media_from_session(db_session, s.id, [p1.file_key])
    db_session.commit()

    remaining = [j.media_file.file_key for j in s.media_joins]
    assert remaining == [p2.file_key]


def test_orphan_delete_skips_referenced_files(db_session, person):
    from flexlog.services.media import orphan_delete_media_file
    from flexlog.services.sessions import link_media_to_session
    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "f" * 64)
    link_media_to_session(db_session, s.id, {"photo": [p1.file_key],
                                              "audio": [], "video": []})
    db_session.commit()

    deleted = orphan_delete_media_file(db_session, p1.file_key)
    assert deleted is False

    from flexlog.db.models import MediaFile
    from sqlalchemy import select
    still_there = db_session.execute(
        select(MediaFile).where(MediaFile.file_key == p1.file_key)
    ).scalar_one_or_none()
    assert still_there is not None


def test_orphan_delete_removes_unreferenced_files(db_session, person, tmp_path, monkeypatch):
    from flexlog.services.media import orphan_delete_media_file
    mf = _create_media_file(db_session, "photo", "9" * 64)
    db_session.commit()

    deleted = orphan_delete_media_file(db_session, mf.file_key)
    assert deleted is True

    from flexlog.db.models import MediaFile
    from sqlalchemy import select
    assert db_session.execute(
        select(MediaFile).where(MediaFile.file_key == mf.file_key)
    ).scalar_one_or_none() is None


def test_link_is_idempotent_on_already_linked_pairs(db_session, person):
    """Edit form pattern: existing media's hidden inputs are re-submitted
    alongside newly-uploaded ones. The duplicate file_keys must not trip
    the UNIQUE constraint on session_media(session_id, media_file_id) —
    they should be silently skipped, and only genuinely new pairs get
    INSERTed."""
    from flexlog.services.sessions import link_media_to_session

    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "a" * 64)
    p2 = _create_media_file(db_session, "photo", "b" * 64)

    # First link: just p1
    created1, unknown1 = link_media_to_session(db_session, s.id, {
        "photo": [p1.file_key], "audio": [], "video": [],
    })
    db_session.commit()
    assert created1 == 1
    assert unknown1 == []
    assert len(s.media_joins) == 1

    # Second link: re-submit p1 (existing) + p2 (new). Must succeed without
    # collision; only p2 should result in a new SessionMedia row.
    created2, unknown2 = link_media_to_session(db_session, s.id, {
        "photo": [p1.file_key, p2.file_key], "audio": [], "video": [],
    })
    db_session.commit()
    assert created2 == 1
    assert unknown2 == []
    assert len(s.media_joins) == 2


def test_link_dedupes_within_a_single_call(db_session, person):
    """If the form somehow submits the same file_key twice in one POST
    (e.g. due to a JS bug), the second occurrence should be silently
    skipped rather than blowing up the whole save."""
    from flexlog.services.sessions import link_media_to_session

    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "f" * 64)

    created, unknown = link_media_to_session(db_session, s.id, {
        "photo": [p1.file_key, p1.file_key],  # same key twice
        "audio": [], "video": [],
    })
    db_session.commit()
    assert created == 1
    assert unknown == []
    assert len(s.media_joins) == 1
