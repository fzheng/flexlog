import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from flexlog.db import Base, make_engine, make_session_factory
from flexlog.db.models import (
    MediaFile,
    Person,
    Session as SessionModel,
    SessionLink,
    SessionMedia,
)


def _key() -> str:
    return os.urandom(32).hex()


@pytest.fixture
def session(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path, _key())
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s


def _setup_session(s, link_thumbnail_id=None):
    p = Person(id="p1", alias="Alice")
    s.add(p)
    sess = SessionModel(id="s1", person_id="p1", session_date="2026-04-15")
    s.add(sess)
    if link_thumbnail_id is not None:
        s.add(SessionLink(id="l1", session_id="s1", url="https://example.com", thumbnail_media_id=link_thumbnail_id))
    s.commit()
    return p, sess


def test_create_all_registers_media_tables(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path, _key())
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {"media_file", "session_media"} <= names


def test_can_insert_media_file(session):
    mf = MediaFile(
        id="m1",
        sha256="a" * 64,
        file_key="aa/aa/" + ("a" * 64) + ".jpg",
        media_type="photo",
        original_filename="vacation.jpg",
        mime_type="image/jpeg",
        file_size_bytes=12345,
    )
    session.add(mf)
    session.commit()
    got = session.get(MediaFile, "m1")
    assert got is not None
    assert got.sha256 == "a" * 64
    assert got.media_type == "photo"
    assert got.created_at is not None


def test_media_file_sha256_unique(session):
    a = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    b = MediaFile(id="m2", sha256="a" * 64, file_key="aa/aa/y.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(a); session.commit()
    session.add(b)
    with pytest.raises(IntegrityError):
        session.commit()


def test_media_file_required_fields(session):
    bad = MediaFile(id="m1", sha256=None, file_key="x", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)  # type: ignore[arg-type]
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_session_media_links_session_and_media(session):
    _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf); session.commit()
    sm = SessionMedia(id="sm1", session_id="s1", media_file_id="m1", sort_order=0)
    session.add(sm); session.commit()
    rows = session.execute(text("SELECT session_id, media_file_id FROM session_media")).all()
    assert rows == [("s1", "m1")]


def test_session_media_unique_constraint(session):
    """A session can't have the same media file twice."""
    _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1"))
    session.commit()
    session.add(SessionMedia(id="sm2", session_id="s1", media_file_id="m1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_session_cascades_session_media(session):
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1"))
    session.commit()
    session.delete(sess); session.commit()
    # Join row gone, media_file row STILL THERE (soft-unlink semantics per spec §5)
    assert session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM media_file")).scalar() == 1


def test_deleting_media_file_cascades_session_media(session):
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1"))
    session.commit()
    session.delete(mf); session.commit()
    # Join row gone, session row STILL THERE
    assert session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM session")).scalar() == 1


def test_deleting_media_file_sets_avatar_media_id_to_null(session):
    """Hard-delete from Media Library SETs NULL on Person.avatar_media_id."""
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf); session.commit()
    p = Person(id="p1", alias="Alice", avatar_media_id="m1")
    session.add(p); session.commit()
    session.delete(mf); session.commit()
    refreshed = session.get(Person, "p1")
    assert refreshed is not None
    assert refreshed.avatar_media_id is None


def test_deleting_media_file_sets_thumbnail_media_id_to_null(session):
    """Hard-delete from Media Library SETs NULL on SessionLink.thumbnail_media_id."""
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionLink(id="l1", session_id="s1", url="https://example.com", thumbnail_media_id="m1"))
    session.commit()
    session.delete(mf); session.commit()
    refreshed_link = session.get(SessionLink, "l1")
    assert refreshed_link is not None
    assert refreshed_link.thumbnail_media_id is None


def test_session_media_relationship_navigates(session):
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1", sort_order=0))
    session.commit()
    refreshed = session.get(SessionModel, "s1")
    assert [m.media_file_id for m in refreshed.media_joins] == ["m1"]
    # And convenience relationship to the underlying MediaFile
    assert [j.media_file.media_type for j in refreshed.media_joins] == ["photo"]
