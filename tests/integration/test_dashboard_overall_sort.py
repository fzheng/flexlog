"""Dashboard avg_overall column + sort=overall default."""
from __future__ import annotations


def _make_with_ratings(db_session, alias, sessions_ratings):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias=alias, tag_input="")
    db_session.commit()
    for i, ratings in enumerate(sessions_ratings):
        create_session(
            db_session, person_id=p.id,
            session_date=f"2026-01-{i+1:02d}",
            ratings=ratings, notes=None, link_urls=[],
        )
    db_session.commit()
    return p


def test_dashboard_default_sort_is_overall(authed_client):
    body = authed_client.get("/").get_data(as_text=True)
    # The "overall" option in the sort select should be present + selected.
    assert 'value="overall"' in body
    # Tolerant for whitespace variations between value and selected
    import re
    m = re.search(r'value="overall"[^>]*selected', body)
    assert m is not None, "overall option should be the selected default"


def test_dashboard_sort_by_overall_orders_descending(authed_client, db_session):
    # Single-dim config (energy, weight 1.0). Overall = energy value.
    _make_with_ratings(db_session, "Alice", [{"energy": 5}, {"energy": 4}])  # avg 4.5
    _make_with_ratings(db_session, "Bob",   [{"energy": 2}])                  # avg 2.0
    _make_with_ratings(db_session, "Carol", [])                                # None

    resp = authed_client.get("/?sort=overall")
    body = resp.get_data(as_text=True)
    a = body.index("Alice")
    b = body.index("Bob")
    c = body.index("Carol")
    assert a < b < c  # Alice (4.5) first, Bob (2.0), Carol (no sessions) last


def test_dashboard_renders_overall_column(authed_client, db_session):
    _make_with_ratings(db_session, "Alice", [{"energy": 4}])
    body = authed_client.get("/").get_data(as_text=True)
    # Alice's card shows the avg_overall
    assert "4.0" in body


def test_dashboard_no_sessions_renders_person(authed_client, db_session):
    _make_with_ratings(db_session, "Carol", [])
    body = authed_client.get("/").get_data(as_text=True)
    assert "Carol" in body
