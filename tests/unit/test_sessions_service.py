import json

import pytest

from flexlog.db.models import Person, Session as SessionModel
from flexlog.services.people import create_person
from flexlog.services.sessions import (
    SessionNotFoundError,
    create_session,
    delete_session,
    get_session,
    list_sessions_for_person,
    split_custom_ratings,
    update_session,
)


def _person(db_session, alias="Alice"):
    p = create_person(db_session, alias=alias, tag_input="")
    db_session.commit()
    return p


def test_create_session_minimal(db_session):
    p = _person(db_session)
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings={},
        notes=None,
        links=[],
    )
    db_session.commit()
    assert s.id
    assert s.person_id == p.id
    assert s.session_date == "2026-04-15"
    assert s.overall_score == 4
    assert s.notes is None
    assert s.links == []
    assert s.custom_ratings_json in ("{}", None) or s.custom_ratings_json == "{}"


def test_create_session_with_full_payload(db_session):
    p = _person(db_session)
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=5,
        custom_ratings={"clarity": 4, "depth": 3},
        notes="深入交流",  # Chinese — UTF-8 round-trip
        links=[
            {"url": "https://example.com", "label": "Reference"},
            {"url": "https://other.com", "label": ""},
        ],
    )
    db_session.commit()
    refreshed = get_session(db_session, s.id)
    assert refreshed.notes == "深入交流"
    assert json.loads(refreshed.custom_ratings_json) == {"clarity": 4, "depth": 3}
    urls = [li.url for li in refreshed.links]
    assert urls == ["https://example.com", "https://other.com"]


def test_create_session_alias_required_via_person_id(db_session):
    """Creating against a missing person id must error cleanly."""
    with pytest.raises(ValueError, match="person"):
        create_session(
            db_session,
            person_id="nope",
            session_date="2026-04-15",
            overall_score=3,
            custom_ratings={},
            notes=None,
            links=[],
        )


def test_create_session_score_out_of_range_rejected(db_session):
    p = _person(db_session)
    with pytest.raises(ValueError, match="overall_score"):
        create_session(
            db_session,
            person_id=p.id,
            session_date="2026-04-15",
            overall_score=6,
            custom_ratings={},
            notes=None,
            links=[],
        )
    with pytest.raises(ValueError, match="overall_score"):
        create_session(
            db_session,
            person_id=p.id,
            session_date="2026-04-15",
            overall_score=-1,
            custom_ratings={},
            notes=None,
            links=[],
        )


def test_create_session_date_format_validated(db_session):
    p = _person(db_session)
    with pytest.raises(ValueError, match="session_date"):
        create_session(
            db_session,
            person_id=p.id,
            session_date="04/15/2026",
            overall_score=3,
            custom_ratings={},
            notes=None,
            links=[],
        )


def test_create_session_drops_empty_link_rows(db_session):
    """Empty/whitespace link rows from the form must be skipped."""
    p = _person(db_session)
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=3,
        custom_ratings={},
        notes=None,
        links=[
            {"url": "  ", "label": ""},
            {"url": "", "label": "label only"},
            {"url": "https://kept.com", "label": ""},
        ],
    )
    db_session.commit()
    assert [li.url for li in s.links] == ["https://kept.com"]


def test_get_session_returns_none_when_missing(db_session):
    assert get_session(db_session, "nope") is None


def test_list_sessions_for_person_orders_newest_first(db_session):
    p = _person(db_session)
    create_session(db_session, person_id=p.id, session_date="2026-03-01", overall_score=3, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-05-01", overall_score=4, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-04-01", overall_score=5, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    rows = list_sessions_for_person(db_session, p.id)
    assert [s.session_date for s in rows] == ["2026-05-01", "2026-04-01", "2026-03-01"]


def test_list_sessions_for_person_empty(db_session):
    p = _person(db_session)
    assert list_sessions_for_person(db_session, p.id) == []


def test_update_session_changes_every_field(db_session):
    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={"clarity": 2}, notes="old", links=[{"url": "https://old.com", "label": "Old"}])
    db_session.commit()
    update_session(
        db_session,
        s.id,
        session_date="2026-05-20",
        overall_score=5,
        custom_ratings={"clarity": 4, "depth": 3},
        notes="new",
        links=[{"url": "https://new.com", "label": "New"}],
    )
    db_session.commit()
    refreshed = get_session(db_session, s.id)
    assert refreshed.session_date == "2026-05-20"
    assert refreshed.overall_score == 5
    assert json.loads(refreshed.custom_ratings_json) == {"clarity": 4, "depth": 3}
    assert refreshed.notes == "new"
    assert [li.url for li in refreshed.links] == ["https://new.com"]


def test_update_session_clearing_links(db_session):
    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[{"url": "https://a.com"}])
    db_session.commit()
    update_session(db_session, s.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    refreshed = get_session(db_session, s.id)
    assert refreshed.links == []


def test_update_session_missing_raises(db_session):
    with pytest.raises(SessionNotFoundError):
        update_session(db_session, "nope", session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[])


def test_delete_session_removes_row(db_session):
    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    delete_session(db_session, s.id)
    db_session.commit()
    assert get_session(db_session, s.id) is None


def test_delete_session_cascades_links(db_session):
    from sqlalchemy import text

    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[{"url": "https://a.com"}, {"url": "https://b.com"}])
    db_session.commit()
    delete_session(db_session, s.id)
    db_session.commit()
    assert db_session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 0


def test_delete_session_missing_raises(db_session):
    with pytest.raises(SessionNotFoundError):
        delete_session(db_session, "nope")


# split_custom_ratings: takes the stored JSON string and the current list of
# enabled rating dimensions, returns (current_pairs, archived_pairs).


def test_split_custom_ratings_only_current(db_session):
    """Stored values for currently-enabled IDs render in current; nothing archived."""
    enabled_ids = ["clarity", "depth"]
    stored = '{"clarity": 4, "depth": 3}'
    current, archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("clarity", 4), ("depth", 3)]
    assert archived == []


def test_split_custom_ratings_extras_archived(db_session):
    """Stored IDs no longer in config render under archived."""
    enabled_ids = ["clarity"]
    stored = '{"clarity": 4, "removed_dim": 2}'
    current, archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("clarity", 4)]
    assert archived == [("removed_dim", 2)]


def test_split_custom_ratings_missing_current_omitted(db_session):
    """Currently-enabled IDs with no stored value are NOT included in current."""
    enabled_ids = ["clarity", "depth"]
    stored = '{"clarity": 4}'
    current, archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("clarity", 4)]
    assert archived == []


def test_split_custom_ratings_handles_null_or_empty_json(db_session):
    enabled_ids = ["clarity"]
    assert split_custom_ratings(None, enabled_ids) == ([], [])
    assert split_custom_ratings("", enabled_ids) == ([], [])
    assert split_custom_ratings("{}", enabled_ids) == ([], [])


def test_split_custom_ratings_preserves_config_order(db_session):
    """Current pairs follow the order of enabled_ids, not insertion order in JSON."""
    enabled_ids = ["depth", "clarity"]
    stored = '{"clarity": 4, "depth": 3}'
    current, _archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("depth", 3), ("clarity", 4)]


def test_split_custom_ratings_handles_malformed_json(db_session):
    from flexlog.services.sessions import split_custom_ratings
    assert split_custom_ratings("not json", ["clarity"]) == ([], [])
    assert split_custom_ratings("{not closed", ["clarity"]) == ([], [])


def test_split_custom_ratings_handles_non_dict_json(db_session):
    from flexlog.services.sessions import split_custom_ratings
    assert split_custom_ratings("[1, 2, 3]", ["clarity"]) == ([], [])
    assert split_custom_ratings('"a string"', ["clarity"]) == ([], [])
    assert split_custom_ratings("42", ["clarity"]) == ([], [])
