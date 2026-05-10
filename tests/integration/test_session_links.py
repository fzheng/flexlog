def _make(db_session, links):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings={},
        notes=None,
        links=links,
    )
    db_session.commit()
    return p, s


def test_delete_link_removes_only_that_row(authed_client, db_session):
    from flexlog.db.models import SessionLink

    p, s = _make(db_session, [{"url": "https://a.com", "label": "A"}, {"url": "https://b.com", "label": "B"}])
    target = [li for li in s.links if li.url == "https://a.com"][0]
    other_id = [li.id for li in s.links if li.url == "https://b.com"][0]

    resp = authed_client.post(f"/session_links/{target.id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    # Redirects to the session edit page
    assert f"/sessions/{s.id}/edit" in resp.headers["Location"]

    db_session.expire_all()
    assert db_session.get(SessionLink, target.id) is None
    assert db_session.get(SessionLink, other_id) is not None


def test_delete_link_404_when_missing(authed_client):
    resp = authed_client.post("/session_links/nope/delete")
    assert resp.status_code == 404
