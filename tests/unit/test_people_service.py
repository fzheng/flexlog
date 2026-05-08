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
