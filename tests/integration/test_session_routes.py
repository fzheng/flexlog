import json


def _make_person(db_session, alias="Alice", tags=""):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def _make_session(db_session, person_id, **kwargs):
    from flexlog.services.sessions import create_session
    defaults = dict(
        session_date="2026-04-15",
        ratings={"energy": 4},
        notes=None,
        link_urls=[],
    )
    defaults.update(kwargs)
    s = create_session(db_session, person_id=person_id, **defaults)
    db_session.commit()
    return s


def test_get_new_session_form(authed_client, db_session):
    p = _make_person(db_session)
    resp = authed_client.get(f"/people/{p.id}/sessions/new")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert p.alias in body
    # Renders enabled rating dimensions from config.json — the v2 default
    # ships "Energy" as the single enabled rating.
    assert "Energy" in body


def test_get_new_session_form_404_when_person_missing(authed_client):
    resp = authed_client.get("/people/nope/sessions/new")
    assert resp.status_code == 404


def test_post_create_session_minimal(authed_client, db_session):
    p = _make_person(db_session)
    resp = authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/sessions/" in resp.headers["Location"]


def test_post_create_session_with_full_payload(authed_client, db_session):
    from flexlog.db.models import Session as SessionRow
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    resp = authed_client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15",
            "notes": "深入的对话",
            "rating_energy": "4",
            # rating_clarity is not enabled in default config so it's ignored
            "link_urls": ["https://example.com", "https://other.com", ""],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    rows = db_session.query(SessionRow).filter_by(person_id=p.id).all()
    assert len(rows) == 1
    sid = rows[0].id
    s = get_session(db_session, sid)
    assert s.notes == "深入的对话"
    assert json.loads(s.ratings_json) == {"energy": 4}
    # Empty link row dropped
    assert [li.url for li in s.links] == ["https://example.com", "https://other.com"]


def test_post_create_session_missing_date_rerenders(authed_client, db_session):
    p = _make_person(db_session)
    resp = authed_client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": ""},
    )
    assert resp.status_code == 400


def test_get_session_detail(authed_client, db_session):
    p = _make_person(db_session)
    s = _make_session(
        db_session, p.id,
        ratings={"energy": 4}, notes="hello",
        link_urls=["https://example.com"],
    )
    resp = authed_client.get(f"/sessions/{s.id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-04-15" in body
    assert "hello" in body
    assert "https://example.com" in body
    # Current rating renders
    assert "Energy" in body  # label from the default v2 config


def test_get_session_detail_404(authed_client):
    resp = authed_client.get("/sessions/nope")
    assert resp.status_code == 404


def test_get_session_edit_prefills(authed_client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, notes="prefilled", link_urls=["https://x.com"])
    resp = authed_client.get(f"/sessions/{s.id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "prefilled" in body
    assert "https://x.com" in body


def test_post_update_session(authed_client, db_session):
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    s = _make_session(db_session, p.id, ratings={"energy": 2}, notes="old")
    resp = authed_client.post(
        f"/sessions/{s.id}",
        data={
            "session_date": "2026-05-20",
            "rating_energy": "5",
            "notes": "new",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db_session.expire_all()
    refreshed = get_session(db_session, s.id)
    assert json.loads(refreshed.ratings_json) == {"energy": 5}
    assert refreshed.notes == "new"
    assert refreshed.session_date == "2026-05-20"


def test_post_update_session_404_when_missing(authed_client):
    resp = authed_client.post("/sessions/nope", data={"session_date": "2026-04-15"})
    assert resp.status_code == 404


def test_xss_in_notes_is_escaped(authed_client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, notes="<script>alert(1)</script>")
    resp = authed_client.get(f"/sessions/{s.id}")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_archived_ratings_render_separately(authed_client, db_session, app):
    """Stored ratings whose IDs are no longer in config show under archived."""
    from flexlog.services.sessions import create_session

    p = _make_person(db_session)
    create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        # energy is enabled in the default config; removed_dim is not
        ratings={"energy": 4, "removed_dim": 2},
        notes=None,
        link_urls=[],
    )
    db_session.commit()

    rows = db_session.query(
        __import__("flexlog.db.models", fromlist=["Session"]).Session
    ).all()
    sid = rows[0].id
    resp = authed_client.get(f"/sessions/{sid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Both rating IDs should appear, but in different sections (the template
    # uses a heading like "Archived ratings" for the latter group).
    assert "Energy" in body  # current label
    assert "removed_dim" in body  # archived raw id


def test_post_delete_session(authed_client, db_session):
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    s = _make_session(db_session, p.id)
    resp = authed_client.post(f"/sessions/{s.id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    # Redirects to person detail
    assert f"/people/{p.id}" in resp.headers["Location"]
    assert get_session(db_session, s.id) is None


def test_post_delete_session_404(authed_client):
    resp = authed_client.post("/sessions/nope/delete")
    assert resp.status_code == 404


def test_delete_session_cascades_links(authed_client, db_session):
    from sqlalchemy import text

    p = _make_person(db_session)
    s = _make_session(db_session, p.id, link_urls=["https://a.com", "https://b.com"])
    authed_client.post(f"/sessions/{s.id}/delete")
    db_session.expire_all()
    assert db_session.execute(
        text("SELECT COUNT(*) FROM session_link WHERE session_id = :sid"),
        {"sid": s.id},
    ).scalar() == 0


# ---------------------------------------------------------------- _build_existing_links_for_template + error rerender


def test_create_session_400_rerenders_with_unsafe_url_dropped(
    csrf_authed_client, csrf_person, csrf_db_session,
):
    """On a form-validation error (bad session_date), the page re-renders
    with the user's submitted URLs filtered through is_safe_link_url —
    a javascript: URL pasted in is dropped from the re-render output."""
    import re
    # Grab CSRF token from the new-session form first
    new_url = f"/people/{csrf_person.id}/sessions/new"
    body = csrf_authed_client.get(new_url).get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)

    resp = csrf_authed_client.post(
        f"/people/{csrf_person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "not-a-date",  # forces validation failure
            "notes": "",
            "link_urls": ["javascript:alert(1)", "https://example.com/ok"],
            "link_thumb_keys": ["", ""],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    rerender = resp.get_data(as_text=True)
    assert "https://example.com/ok" in rerender
    assert "javascript:alert(1)" not in rerender


def test_update_session_with_unknown_photo_key_422(
    csrf_authed_client, csrf_person, csrf_db_session,
):
    """POST /sessions/<id> with a photo_keys list referencing a
    nonexistent MediaFile must return 422 + flash the stale-keys
    warning. The route's link_media_to_session catches the unknown
    list and rolls back."""
    import re
    from flexlog.services.sessions import create_session

    s = create_session(
        csrf_db_session, person_id=csrf_person.id, session_date="2026-05-18",
        ratings={"energy": 4}, notes=None,
        link_urls=[], link_thumb_keys=[],
    )
    csrf_db_session.commit()
    sid = s.id

    edit_body = csrf_authed_client.get(f"/sessions/{sid}/edit").get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', edit_body).group(1)

    resp = csrf_authed_client.post(
        f"/sessions/{sid}",
        data={
            "csrf_token": token,
            "session_date": "2026-05-18",
            "notes": "",
            "rating_energy": "4",
            "photo_keys": ["nonexistent-key-abc123"],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 422
    body = resp.get_data(as_text=True)
    assert "stale key" in body.lower() or "no longer available" in body.lower()


def test_update_session_400_with_unsafe_url_drops_in_rerender(
    csrf_authed_client, csrf_person, csrf_db_session,
):
    """Same as the create-side test but for the update form path."""
    import re
    from flexlog.services.sessions import create_session

    s = create_session(
        csrf_db_session, person_id=csrf_person.id, session_date="2026-05-18",
        ratings={"energy": 4}, notes=None,
        link_urls=[], link_thumb_keys=[],
    )
    csrf_db_session.commit()

    edit_body = csrf_authed_client.get(f"/sessions/{s.id}/edit").get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', edit_body).group(1)

    resp = csrf_authed_client.post(
        f"/sessions/{s.id}",
        data={
            "csrf_token": token,
            "session_date": "not-a-date",  # validation failure
            "notes": "",
            "rating_energy": "4",
            "link_urls": ["data:text/html,<x>", "https://example.com/ok"],
            "link_thumb_keys": ["", ""],
        },
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "https://example.com/ok" in body
    assert "data:text/html" not in body


def test_link_destroy_404_for_unknown_link(csrf_authed_client):
    """POST /session_links/<unknown_id>/delete returns 404."""
    import re
    # Grab a CSRF token from any GET page
    body = csrf_authed_client.get("/dashboard").get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)
    resp = csrf_authed_client.post(
        "/session_links/nonexistent-link-xyz/delete",
        data={"csrf_token": token},
    )
    assert resp.status_code == 404
