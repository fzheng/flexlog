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
    create_session(db_session, person_id=a.id, session_date="2026-01-15", ratings={"energy": 3}, notes="", link_urls=[])
    create_session(db_session, person_id=b.id, session_date="2026-03-10", ratings={"energy": 4}, notes="", link_urls=[])
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
        create_session(db_session, person_id=a.id, session_date=d, ratings={"energy": 3}, notes="", link_urls=[])
    create_session(db_session, person_id=b.id, session_date="2026-01-01", ratings={"energy": 3}, notes="", link_urls=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="session_count")
    assert [r.person.alias for r in rows] == ["A", "B"]


def test_list_dashboard_rows_sort_custom_dim_nulls_last(db_session):
    from flexlog.services.people import create_person, list_dashboard_rows
    from flexlog.services.sessions import create_session
    a = create_person(db_session, alias="A", tag_input="")
    b = create_person(db_session, alias="B", tag_input="")
    c = create_person(db_session, alias="C", tag_input="")  # no sessions
    db_session.commit()
    create_session(db_session, person_id=a.id, session_date="2026-01-01", ratings={"energy": 4}, notes="", link_urls=[])
    create_session(db_session, person_id=b.id, session_date="2026-01-01", ratings={"energy": 2}, notes="", link_urls=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="custom:energy")
    # A (avg 4.0) before B (avg 2.0) before C (no rating, NULLs last)
    assert [r.person.alias for r in rows] == ["A", "B", "C"]


def test_apply_tags_dedups_same_tag_in_input(db_session):
    """Same tag listed twice in tag_input (different casing) must collapse
    to one PersonTag — exercises the `if sl in existing_slugs: continue`
    branch in _apply_tags."""
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    # Add Engineer once
    update_person(db_session, p.id, alias="Alice", tag_input="Engineer")
    db_session.commit()
    # Now apply tag_input that already includes Engineer (it should not
    # try to re-create the join; should hit the `continue` branch).
    update_person(db_session, p.id, alias="Alice", tag_input="Engineer, Engineer, ENGINEER")
    db_session.commit()
    refreshed = get_person(db_session, p.id)
    slugs = [t.slug for t in refreshed.tags]
    assert slugs == ["engineer"]


def test_list_dashboard_rows_unknown_sort_falls_back_to_alias(db_session):
    """sort='garbage' should fall back to alphabetical alias sort, not
    crash. Exercises the trailing `return sorted(rows, key=alias_key)` in
    _sort_rows that runs when no branch matches."""
    from flexlog.services.people import list_dashboard_rows
    create_person(db_session, alias="Charlie", tag_input="")
    create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="not-a-real-sort-key")
    assert [r.person.alias for r in rows] == ["Alice", "Charlie"]


def test_custom_dim_averages_skips_empty_json(db_session):
    """Sessions with ratings_json='' or NULL must be ignored by the
    custom-dim averager — exercises the `if not raw: continue` branch."""
    from sqlalchemy import text
    from flexlog.services.people import _custom_dim_averages
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias="A", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-01-01",
                       ratings={}, notes="", link_urls=[])
    db_session.commit()
    # _serialize_ratings({}) returns "{}", which is truthy. Force the column
    # to literal NULL via raw SQL to exercise the `if not raw: continue` path.
    db_session.execute(
        text("UPDATE session SET ratings_json = NULL WHERE id = :sid"),
        {"sid": s.id},
    )
    db_session.commit()
    out = _custom_dim_averages(db_session, "any_dim")
    assert out == {}


def test_custom_dim_averages_skips_invalid_json(db_session):
    """If ratings_json is malformed, the averager must skip the row,
    not crash. Exercises the json.loads except-branch."""
    from sqlalchemy import text
    from flexlog.services.people import _custom_dim_averages
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias="A", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-01-01",
                       ratings={}, notes="", link_urls=[])
    db_session.commit()
    # Smash the JSON column to broken bytes via raw SQL so we don't have
    # to bypass services/sessions validation
    db_session.execute(
        text("UPDATE session SET ratings_json = :raw WHERE id = :sid"),
        {"raw": "{{not json", "sid": s.id},
    )
    db_session.commit()
    out = _custom_dim_averages(db_session, "any_dim")
    assert out == {}


def test_custom_dim_averages_skips_non_dict_json(db_session):
    """If ratings_json parses to a list / number / string, the
    averager must skip the row. Exercises the isinstance(data, dict) branch."""
    from sqlalchemy import text
    from flexlog.services.people import _custom_dim_averages
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias="A", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-01-01",
                       ratings={}, notes="", link_urls=[])
    db_session.commit()
    db_session.execute(
        text("UPDATE session SET ratings_json = :raw WHERE id = :sid"),
        {"raw": "[1, 2, 3]", "sid": s.id},
    )
    db_session.commit()
    out = _custom_dim_averages(db_session, "any_dim")
    assert out == {}


def test_custom_dim_averages_skips_missing_dim(db_session):
    """If a session's ratings dict is valid JSON but doesn't carry
    the requested dim_id, that session contributes nothing to the average."""
    from flexlog.services.people import _custom_dim_averages
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias="A", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-01-01",
                   ratings={"other_dim": 4}, notes="", link_urls=[])
    db_session.commit()
    out = _custom_dim_averages(db_session, "missing_dim")
    assert out == {}


def test_custom_dim_averages_skips_non_numeric_value(db_session):
    """If a dim's value is non-numeric (would fail float(v)), the row is
    skipped, not the whole call. Exercises the float() except-branch."""
    from sqlalchemy import text
    from flexlog.services.people import _custom_dim_averages
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias="A", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-01-01",
                       ratings={}, notes="", link_urls=[])
    db_session.commit()
    # Inject a string value directly into the JSON column
    db_session.execute(
        text("UPDATE session SET ratings_json = :raw WHERE id = :sid"),
        {"raw": '{"my_dim": "not-a-number"}', "sid": s.id},
    )
    db_session.commit()
    out = _custom_dim_averages(db_session, "my_dim")
    assert out == {}


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
    create_session(db_session, person_id=a.id, session_date="2026-01-01",
                   ratings={"dim_x": 5}, notes="", link_urls=[])
    create_session(db_session, person_id=a.id, session_date="2026-01-02",
                   ratings={"dim_x": 3}, notes="", link_urls=[])
    # B: avg of dim_x = 5.0 (one session)
    create_session(db_session, person_id=b.id, session_date="2026-01-01",
                   ratings={"dim_x": 5}, notes="", link_urls=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="", sort="custom:dim_x")
    # B (5.0) > A (4.0) > C (no dim_x — sorts last)
    assert [r.person.alias for r in rows] == ["B", "A", "C"]
