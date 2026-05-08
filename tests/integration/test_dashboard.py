def _create(db_session, alias, tags=""):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def test_dashboard_empty_state(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Interview Log" in body  # app name still rendered
    assert "Guests" in body  # entity plural
    # Empty state copy from config
    assert "No guests yet. Add your first guest to begin." in body
    # New-person button is now wired to /people/new (no longer #)
    assert "/people/new" in body


def test_dashboard_lists_people(client, db_session):
    _create(db_session, "Alice", "Engineer")
    _create(db_session, "Bob", "Coach")
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "Alice" in body
    assert "Bob" in body
    # Tag chips render
    assert "Engineer" in body
    assert "Coach" in body
    # Person cards link to detail pages
    from flexlog.db.models import Person
    alice = db_session.query(Person).filter_by(alias="Alice").one()
    assert f"/people/{alice.id}" in body


def test_dashboard_search_by_alias(client, db_session):
    _create(db_session, "Alice")
    _create(db_session, "Bob")
    resp = client.get("/?q=alice")
    body = resp.get_data(as_text=True)
    assert "Alice" in body
    assert "Bob" not in body


def test_dashboard_search_by_tag(client, db_session):
    _create(db_session, "Alice", "Engineer")
    _create(db_session, "Bob", "Coach")
    resp = client.get("/?q=coach")
    body = resp.get_data(as_text=True)
    assert "Bob" in body
    assert "Alice" not in body


def test_dashboard_search_no_match(client, db_session):
    _create(db_session, "Alice", "Engineer")
    resp = client.get("/?q=zebra")
    body = resp.get_data(as_text=True)
    assert "Alice" not in body
    # Search-empty state shown — accept any of three plausible phrasings
    body_lc = body.lower()
    assert ("no guests yet" in body_lc) or ("no matches" in body_lc) or ("0 results" in body_lc)


def test_dashboard_xss_safe_alias(client, db_session):
    _create(db_session, "<script>alert(1)</script>", "")
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_dashboard_search_query_echoed_safely(client):
    """The search query is echoed back into the input field; ensure XSS-safe."""
    resp = client.get("/?q=<img+onerror=x>")
    body = resp.get_data(as_text=True)
    # The literal HTML must not appear unescaped
    assert "<img onerror=x>" not in body
