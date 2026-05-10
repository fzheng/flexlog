import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from flexlog.db import Base, make_engine, make_session_factory
from flexlog.db.models import Person, PersonTag, Tag


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


def test_create_all_registers_three_tables(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path, _key())
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    assert {"person", "tag", "person_tag"} <= names


def test_create_all_is_idempotent(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path, _key())
    Base.metadata.create_all(engine)
    Base.metadata.create_all(engine)  # second call must not raise
    inspector = inspect(engine)
    assert "person" in inspector.get_table_names()


def test_can_insert_person(session):
    p = Person(id=str(uuid.uuid4()), alias="Alice", avatar_media_id=None)
    session.add(p)
    session.commit()
    got = session.get(Person, p.id)
    assert got is not None
    assert got.alias == "Alice"
    assert got.avatar_media_id is None
    assert got.created_at is not None
    assert got.updated_at is not None


def test_person_id_is_unique(session):
    p1 = Person(id="dup-id", alias="A")
    p2 = Person(id="dup-id", alias="B")
    session.add(p1)
    session.commit()
    session.add(p2)
    with pytest.raises(IntegrityError):
        session.commit()


def test_can_insert_tag(session):
    t = Tag(id=str(uuid.uuid4()), name="Engineering", slug="engineering")
    session.add(t)
    session.commit()
    got = session.get(Tag, t.id)
    assert got is not None
    assert got.name == "Engineering"
    assert got.slug == "engineering"


def test_tag_slug_is_unique(session):
    a = Tag(id="ta", name="Engineering", slug="engineering")
    b = Tag(id="tb", name="ENGINEERING", slug="engineering")
    session.add(a)
    session.commit()
    session.add(b)
    with pytest.raises(IntegrityError):
        session.commit()


def test_person_tag_join_links_two(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    join = PersonTag(person_id="p1", tag_id="t1")
    session.add(join)
    session.commit()
    rows = session.execute(text("SELECT person_id, tag_id FROM person_tag")).all()
    assert rows == [("p1", "t1")]


def test_person_tag_composite_pk_dedup(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_person_cascades_into_person_tag(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    # Sanity
    assert session.execute(text("SELECT COUNT(*) FROM person_tag")).scalar() == 1
    session.delete(p)
    session.commit()
    # Cascade: the join row should be gone with the parent
    assert session.execute(text("SELECT COUNT(*) FROM person_tag")).scalar() == 0
    # Tag itself survives — tags are global
    assert session.execute(text("SELECT COUNT(*) FROM tag")).scalar() == 1


def test_deleting_tag_cascades_into_person_tag(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    session.delete(t)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM person_tag")).scalar() == 0
    # Person itself survives
    assert session.execute(text("SELECT COUNT(*) FROM person")).scalar() == 1


def test_person_relationships_navigate_tags(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    refreshed = session.get(Person, "p1")
    # Person.tags exposes the linked Tag rows via the relationship
    assert [tag.name for tag in refreshed.tags] == ["Friend"]


def test_person_alias_required(session):
    p = Person(id="x", alias=None)  # type: ignore[arg-type]
    session.add(p)
    with pytest.raises(IntegrityError):
        session.commit()
