import pytest

from flexlog.services.people import create_person, list_dashboard_rows
from flexlog.services.sessions import create_session


def test_dashboard_rows_empty(db_session):
    assert list_dashboard_rows(db_session, query="") == []


def test_dashboard_rows_person_with_no_sessions(db_session):
    """A person with no sessions still appears, with zero/None aggregates."""
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="")
    assert len(rows) == 1
    row = rows[0]
    assert row.person.alias == "Alice"
    assert row.session_count == 0
    assert row.last_session_date is None
    assert row.avg_overall_score is None


def test_dashboard_rows_aggregates(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-03-01", ratings={"energy": 4}, notes=None, link_urls=[])
    create_session(db_session, person_id=p.id, session_date="2026-04-15", ratings={"energy": 5}, notes=None, link_urls=[])
    create_session(db_session, person_id=p.id, session_date="2026-02-10", ratings={"energy": 3}, notes=None, link_urls=[])
    db_session.commit()

    rows = list_dashboard_rows(db_session, query="")
    assert len(rows) == 1
    row = rows[0]
    assert row.session_count == 3
    assert row.last_session_date == "2026-04-15"
    assert row.avg_overall_score == 4.0  # (4+5+3)/3


def test_dashboard_rows_search_by_alias(db_session):
    a = create_person(db_session, alias="Alice", tag_input="")
    b = create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="alice")
    assert [r.person.alias for r in rows] == ["Alice"]


def test_dashboard_rows_search_by_tag(db_session):
    a = create_person(db_session, alias="Alice", tag_input="Engineer")
    b = create_person(db_session, alias="Bob", tag_input="Coach")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="engineer")
    assert [r.person.alias for r in rows] == ["Alice"]


def test_dashboard_rows_alphabetical_by_alias(db_session):
    create_person(db_session, alias="Charlie", tag_input="")
    create_person(db_session, alias="alice", tag_input="")  # lowercase
    create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="")
    # Case-insensitive alpha order
    assert [r.person.alias for r in rows] == ["alice", "Bob", "Charlie"]


def test_dashboard_rows_does_not_double_count_with_tags(db_session):
    """A person with multiple tags must appear once with correct aggregates."""
    p = create_person(db_session, alias="Alice", tag_input="Engineer, Friend, Coach")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-04-15", ratings={"energy": 4}, notes=None, link_urls=[])
    create_session(db_session, person_id=p.id, session_date="2026-05-01", ratings={"energy": 5}, notes=None, link_urls=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="")
    assert len(rows) == 1
    assert rows[0].session_count == 2  # NOT 6 (sessions × tags)
