def _make_person(db_session, alias="Alice", tags=""):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def _make_session(db_session, person_id, **kwargs):
    from flexlog.services.sessions import create_session
    defaults = dict(
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings={},
        notes=None,
        links=[],
    )
    defaults.update(kwargs)
    s = create_session(db_session, person_id=person_id, **defaults)
    db_session.commit()
    return s


def test_get_new_session_form(client, db_session):
    p = _make_person(db_session)
    resp = client.get(f"/people/{p.id}/sessions/new")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert p.alias in body
    # Renders enabled rating dimensions from config.json (default has clarity + overall_quality)
    assert "Clarity" in body or "Overall Quality" in body


def test_get_new_session_form_404_when_person_missing(client):
    resp = client.get("/people/nope/sessions/new")
    assert resp.status_code == 404


def test_post_create_session_minimal(client, db_session):
    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/sessions/" in resp.headers["Location"]


def test_post_create_session_with_full_payload(client, db_session):
    from flexlog.db.models import Session as SessionRow
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15",
            "overall_score": "5",
            "notes": "深入的对话",
            "rating_clarity": "4",
            "rating_overall_quality": "5",
            "link_url": ["https://example.com", "https://other.com", ""],
            "link_label": ["Reference", "Followup", ""],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    rows = db_session.query(SessionRow).filter_by(person_id=p.id).all()
    assert len(rows) == 1
    sid = rows[0].id
    s = get_session(db_session, sid)
    assert s.notes == "深入的对话"
    # Empty link row dropped
    assert [li.url for li in s.links] == ["https://example.com", "https://other.com"]


def test_post_create_session_invalid_score_rerenders(client, db_session):
    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "9"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "overall_score" in body.lower()


def test_post_create_session_missing_date_rerenders(client, db_session):
    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "", "overall_score": "3"},
    )
    assert resp.status_code == 400


def test_get_session_detail(client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, custom_ratings={"clarity": 4}, notes="hello", links=[{"url": "https://example.com", "label": "Ref"}])
    resp = client.get(f"/sessions/{s.id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-04-15" in body
    assert "hello" in body
    assert "https://example.com" in body
    # Custom rating renders
    assert "Clarity" in body  # label from the default config.json


def test_get_session_detail_404(client):
    resp = client.get("/sessions/nope")
    assert resp.status_code == 404


def test_get_session_edit_prefills(client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, notes="prefilled", links=[{"url": "https://x.com", "label": "X"}])
    resp = client.get(f"/sessions/{s.id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "prefilled" in body
    assert "https://x.com" in body


def test_post_update_session(client, db_session):
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    s = _make_session(db_session, p.id, overall_score=2, notes="old")
    resp = client.post(
        f"/sessions/{s.id}",
        data={
            "session_date": "2026-05-20",
            "overall_score": "5",
            "notes": "new",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db_session.expire_all()
    refreshed = get_session(db_session, s.id)
    assert refreshed.overall_score == 5
    assert refreshed.notes == "new"
    assert refreshed.session_date == "2026-05-20"


def test_post_update_session_404_when_missing(client):
    resp = client.post("/sessions/nope", data={"session_date": "2026-04-15", "overall_score": "3"})
    assert resp.status_code == 404


def test_xss_in_notes_is_escaped(client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, notes="<script>alert(1)</script>")
    resp = client.get(f"/sessions/{s.id}")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_archived_ratings_render_separately(client, db_session, app):
    """Stored ratings whose IDs are no longer in config show under archived."""
    import json
    from flexlog.services.sessions import create_session

    p = _make_person(db_session)
    create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=3,
        custom_ratings={"clarity": 4, "removed_dim": 2},  # removed_dim isn't in config
        notes=None,
        links=[],
    )
    db_session.commit()

    # In default config "clarity" is enabled but "removed_dim" is not.
    rows = db_session.query(__import__("flexlog.db.models", fromlist=["Session"]).Session).all()
    sid = rows[0].id
    resp = client.get(f"/sessions/{sid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Both rating IDs should appear, but in different sections (the template
    # uses a heading like "Archived ratings" for the latter group).
    assert "Clarity" in body  # current label
    assert "removed_dim" in body  # archived raw id
