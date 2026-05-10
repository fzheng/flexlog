import pytest

from flexlog.db.models import Person, Tag
from flexlog.services.people import (
    PersonNotFoundError,
    create_person,
    delete_person,
    get_person,
    list_people,
    search_people,
    update_person,
)


def test_create_person_minimal(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    assert p.id  # UUID assigned
    assert p.alias == "Alice"
    assert p.tags == []


def test_create_person_with_tags(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Engineer, Friend")
    db_session.commit()
    assert sorted(t.name for t in p.tags) == ["Engineer", "Friend"]


def test_create_person_dedup_tags_via_slug(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Engineer, ENGINEER")
    db_session.commit()
    assert len(p.tags) == 1
    assert p.tags[0].slug == "engineer"


def test_create_person_alias_required(db_session):
    with pytest.raises(ValueError, match="alias"):
        create_person(db_session, alias="", tag_input="")
    with pytest.raises(ValueError, match="alias"):
        create_person(db_session, alias="   ", tag_input="")


def test_get_person_returns_none_when_missing(db_session):
    assert get_person(db_session, "nope") is None


def test_get_person_returns_match(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    got = get_person(db_session, p.id)
    assert got is not None
    assert got.id == p.id


def test_list_people_empty(db_session):
    assert list_people(db_session) == []


def test_list_people_alphabetical_by_alias(db_session):
    create_person(db_session, alias="Charlie", tag_input="")
    create_person(db_session, alias="Alice", tag_input="")
    create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    names = [p.alias for p in list_people(db_session)]
    assert names == ["Alice", "Bob", "Charlie"]


def test_search_people_by_alias_substring(db_session):
    create_person(db_session, alias="Alice Smith", tag_input="")
    create_person(db_session, alias="Bob Jones", tag_input="")
    db_session.commit()
    results = search_people(db_session, "alice")
    assert [p.alias for p in results] == ["Alice Smith"]


def test_search_people_by_tag_name(db_session):
    create_person(db_session, alias="Alice", tag_input="Engineer")
    create_person(db_session, alias="Bob", tag_input="Coach")
    db_session.commit()
    results = search_people(db_session, "engineer")
    assert [p.alias for p in results] == ["Alice"]


def test_search_people_by_tag_slug(db_session):
    create_person(db_session, alias="Alice", tag_input="Senior Engineer")
    db_session.commit()
    results = search_people(db_session, "senior-engineer")
    assert [p.alias for p in results] == ["Alice"]


def test_search_people_case_insensitive(db_session):
    create_person(db_session, alias="Alice", tag_input="Engineer")
    db_session.commit()
    assert len(search_people(db_session, "ALICE")) == 1
    assert len(search_people(db_session, "ENGINEER")) == 1


def test_search_people_empty_query_returns_all(db_session):
    create_person(db_session, alias="Alice", tag_input="")
    create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    assert len(search_people(db_session, "")) == 2
    assert len(search_people(db_session, "   ")) == 2


def test_search_people_no_match(db_session):
    create_person(db_session, alias="Alice", tag_input="Engineer")
    db_session.commit()
    assert search_people(db_session, "zebra") == []


def test_search_people_dedups_when_alias_and_tag_both_match(db_session):
    """A person whose alias contains the query AND who has a matching tag must
    appear once, not twice."""
    create_person(db_session, alias="Engineer Bob", tag_input="Engineer")
    db_session.commit()
    results = search_people(db_session, "engineer")
    assert len(results) == 1


def test_update_person_alias_and_tags(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    update_person(db_session, p.id, alias="Alicia", tag_input="Coach, Mentor")
    db_session.commit()
    refreshed = get_person(db_session, p.id)
    assert refreshed.alias == "Alicia"
    assert sorted(t.name for t in refreshed.tags) == ["Coach", "Mentor"]


def test_update_person_clearing_tags(db_session):
    from sqlalchemy import text

    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    update_person(db_session, p.id, alias="Alice", tag_input="")
    db_session.commit()
    refreshed = get_person(db_session, p.id)
    assert refreshed.tags == []
    # The underlying join row must actually be deleted, not just absent
    # from the in-memory collection.
    join_count = db_session.execute(
        text("SELECT COUNT(*) FROM person_tag WHERE person_id = :pid"),
        {"pid": p.id},
    ).scalar()
    assert join_count == 0
    # And the Tag itself survives — tags are global.
    from flexlog.services.tags import list_all_tags
    assert [t.name for t in list_all_tags(db_session)] == ["Friend"]


def test_update_person_alias_required(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    with pytest.raises(ValueError, match="alias"):
        update_person(db_session, p.id, alias="  ", tag_input="")


def test_update_person_missing_raises(db_session):
    with pytest.raises(PersonNotFoundError):
        update_person(db_session, "nope", alias="X", tag_input="")


def test_delete_person_removes_row(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    delete_person(db_session, p.id)
    db_session.commit()
    assert get_person(db_session, p.id) is None


def test_delete_person_does_not_orphan_tag(db_session):
    """Tags are global — deleting a person must not delete their tags."""
    from flexlog.services.tags import list_all_tags

    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    delete_person(db_session, p.id)
    db_session.commit()
    assert [t.name for t in list_all_tags(db_session)] == ["Friend"]


def test_delete_person_missing_raises(db_session):
    with pytest.raises(PersonNotFoundError):
        delete_person(db_session, "nope")


def test_list_dashboard_rows_sort_alias_default(db_session):
    from flexlog.services.people import create_person, list_dashboard_rows
    create_person(db_session, alias="charlie", tag_input="")
    create_person(db_session, alias="alice", tag_input="")
    create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="alias")
    assert [r.person.alias for r in rows] == ["alice", "Bob", "charlie"]


def test_list_dashboard_rows_sort_last_date_nulls_last(db_session):
    from datetime import date
    from flexlog.services.people import create_person, list_dashboard_rows
    from flexlog.services.sessions import create_session
    a = create_person(db_session, alias="A", tag_input="")
    b = create_person(db_session, alias="B", tag_input="")
    c = create_person(db_session, alias="C", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=a.id, session_date="2026-01-15", overall_score=3, notes="", custom_ratings={}, links=[])
    create_session(db_session, person_id=b.id, session_date="2026-03-10", overall_score=4, notes="", custom_ratings={}, links=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="last_date")
    aliases = [r.person.alias for r in rows]
    # B (most recent), A (older), C (no sessions — last)
    assert aliases == ["B", "A", "C"]


def test_list_dashboard_rows_sort_session_count(db_session):
    from flexlog.services.people import create_person, list_dashboard_rows
    from flexlog.services.sessions import create_session
    a = create_person(db_session, alias="A", tag_input="")
    b = create_person(db_session, alias="B", tag_input="")
    db_session.commit()
    for d in ("2026-01-01", "2026-01-02", "2026-01-03"):
        create_session(db_session, person_id=a.id, session_date=d, overall_score=3, notes="", custom_ratings={}, links=[])
    create_session(db_session, person_id=b.id, session_date="2026-01-01", overall_score=3, notes="", custom_ratings={}, links=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="session_count")
    assert [r.person.alias for r in rows] == ["A", "B"]


def test_list_dashboard_rows_sort_avg_score_nulls_last(db_session):
    from flexlog.services.people import create_person, list_dashboard_rows
    from flexlog.services.sessions import create_session
    a = create_person(db_session, alias="A", tag_input="")
    b = create_person(db_session, alias="B", tag_input="")
    c = create_person(db_session, alias="C", tag_input="")  # no sessions
    db_session.commit()
    create_session(db_session, person_id=a.id, session_date="2026-01-01", overall_score=4, notes="", custom_ratings={}, links=[])
    create_session(db_session, person_id=b.id, session_date="2026-01-01", overall_score=2, notes="", custom_ratings={}, links=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="avg_score")
    assert [r.person.alias for r in rows] == ["A", "B", "C"]


def test_list_dashboard_rows_sort_custom_dim_nulls_last(db_session):
    """Custom-dim sort averages a single rating dimension across each person's
    sessions; people without that dim sort last."""
    from flexlog.services.people import create_person, list_dashboard_rows
    from flexlog.services.sessions import create_session
    a = create_person(db_session, alias="A", tag_input="")
    b = create_person(db_session, alias="B", tag_input="")
    c = create_person(db_session, alias="C", tag_input="")  # no sessions at all
    db_session.commit()
    # A: avg of dim_x = (5 + 3) / 2 = 4.0
    create_session(db_session, person_id=a.id, session_date="2026-01-01", overall_score=3,
                   notes="", custom_ratings={"dim_x": 5}, links=[])
    create_session(db_session, person_id=a.id, session_date="2026-01-02", overall_score=3,
                   notes="", custom_ratings={"dim_x": 3}, links=[])
    # B: avg of dim_x = 5.0 (one session)
    create_session(db_session, person_id=b.id, session_date="2026-01-01", overall_score=3,
                   notes="", custom_ratings={"dim_x": 5}, links=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="custom:dim_x")
    # B (5.0) > A (4.0) > C (no dim_x — sorts last)
    assert [r.person.alias for r in rows] == ["B", "A", "C"]
