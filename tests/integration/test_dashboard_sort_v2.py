"""Dashboard sort options are derived from config: only ratings whose
sortable=True appear in the dropdown. Sorting by a sortable dim uses
the Python-side average of that dimension across sessions."""
from __future__ import annotations

import json


def _make_person_with_ratings(db_session, alias, ratings_per_session):
    """Helper: create a person + N sessions with the given ratings dicts."""
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias=alias, tag_input="")
    db_session.commit()
    for i, r in enumerate(ratings_per_session):
        create_session(
            db_session, person_id=p.id,
            session_date=f"2026-01-{i+1:02d}",
            ratings=r, notes=None, link_urls=[],
        )
    db_session.commit()
    return p


def test_dashboard_dropdown_lists_only_sortable_dimensions(authed_client, app):
    # Default bootstrap config has one dimension (energy, sortable=True).
    resp = authed_client.get("/")
    body = resp.get_data(as_text=True)
    assert "custom:energy" in body  # rendered as an <option value="custom:energy">


def test_dashboard_sort_by_custom_dim(authed_client, db_session):
    _make_person_with_ratings(db_session, "Alice", [{"energy": 5}, {"energy": 4}])
    _make_person_with_ratings(db_session, "Bob",   [{"energy": 2}])
    _make_person_with_ratings(db_session, "Carol", [])

    resp = authed_client.get("/?sort=custom:energy")
    body = resp.get_data(as_text=True)
    # Alice (avg 4.5) before Bob (avg 2.0) before Carol (no rating, NULLs last)
    a, b, c = body.index("Alice"), body.index("Bob"), body.index("Carol")
    assert a < b < c
