import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from flexlog.db import Base, make_engine, make_session_factory
from flexlog.db.models import Person, Session as SessionModel, SessionLink


@pytest.fixture
def session(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s


def _person(session, alias="Alice"):
    p = Person(id="p1", alias=alias)
    session.add(p)
    session.commit()
    return p


def test_create_all_registers_session_tables(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {"session", "session_link"} <= names


def test_can_insert_session(session):
    _person(session)
    s = SessionModel(
        id="s1",
        person_id="p1",
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings_json='{"clarity": 5}',
        notes="Good chat.",
    )
    session.add(s)
    session.commit()
    got = session.get(SessionModel, "s1")
    assert got is not None
    assert got.person_id == "p1"
    assert got.session_date == "2026-04-15"
    assert got.overall_score == 4
    assert got.custom_ratings_json == '{"clarity": 5}'
    assert got.notes == "Good chat."
    assert got.created_at is not None
    assert got.updated_at is not None


def test_session_overall_score_check_constraint(session):
    _person(session)
    bad = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=6)
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_session_overall_score_negative_rejected(session):
    _person(session)
    bad = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=-1)
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_session_session_date_required(session):
    _person(session)
    bad = SessionModel(id="s1", person_id="p1", session_date=None, overall_score=3)  # type: ignore[arg-type]
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_person_cascades_sessions(session):
    p = _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.commit()
    session.delete(p)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session")).scalar() == 0


def test_can_insert_session_link(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.commit()
    link = SessionLink(
        id="l1",
        session_id="s1",
        url="https://example.com",
        label="Reference",
        sort_order=0,
    )
    session.add(link)
    session.commit()
    got = session.get(SessionLink, "l1")
    assert got.url == "https://example.com"
    assert got.label == "Reference"
    assert got.thumbnail_media_id is None  # M4 layers the FK


def test_session_link_url_required(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.commit()
    bad = SessionLink(id="l1", session_id="s1", url=None)  # type: ignore[arg-type]
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_session_cascades_links(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.add(SessionLink(id="l1", session_id="s1", url="https://example.com"))
    session.add(SessionLink(id="l2", session_id="s1", url="https://other.com"))
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 2
    session.delete(s)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 0


def test_deleting_person_cascades_through_session_to_links(session):
    p = _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.add(SessionLink(id="l1", session_id="s1", url="https://example.com"))
    session.commit()
    session.delete(p)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 0


def test_person_sessions_relationship_navigates(session):
    p = _person(session)
    session.add(SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3))
    session.add(SessionModel(id="s2", person_id="p1", session_date="2026-05-01", overall_score=4))
    session.commit()
    refreshed = session.get(Person, "p1")
    assert {s.id for s in refreshed.sessions} == {"s1", "s2"}


def test_session_links_relationship_navigates(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.add(SessionLink(id="l1", session_id="s1", url="https://a.com", sort_order=1))
    session.add(SessionLink(id="l2", session_id="s1", url="https://b.com", sort_order=0))
    session.commit()
    refreshed = session.get(SessionModel, "s1")
    # Ordered by sort_order ascending
    assert [li.url for li in refreshed.links] == ["https://b.com", "https://a.com"]
