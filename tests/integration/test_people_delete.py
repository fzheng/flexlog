def _create_person(db_session, alias="Alice", tags=""):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def test_delete_person_with_correct_alias_succeeds(authed_client, db_session):
    from flexlog.services.people import get_person

    p = _create_person(db_session, alias="Alice")
    resp = authed_client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": "Alice"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # Redirects to the dashboard (the post-MVP auth feature moved it from
    # / to /dashboard; either is acceptable as a "back home" target).
    loc = resp.headers["Location"]
    assert loc.endswith("/") or loc.endswith("/dashboard")
    assert get_person(db_session, p.id) is None


def test_delete_person_with_wrong_alias_rerenders_with_error(authed_client, db_session):
    from flexlog.services.people import get_person

    p = _create_person(db_session, alias="Alice")
    resp = authed_client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": "Bob"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "alias" in body.lower()
    # Person must still exist
    assert get_person(db_session, p.id) is not None


def test_delete_person_with_empty_alias_rerenders_with_error(authed_client, db_session):
    p = _create_person(db_session, alias="Alice")
    resp = authed_client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": ""},
    )
    assert resp.status_code == 400


def test_delete_person_404_when_missing(authed_client):
    resp = authed_client.post("/people/no-such-id/delete", data={"confirm_alias": "X"})
    assert resp.status_code == 404


def test_delete_person_alias_check_is_case_sensitive(authed_client, db_session):
    """The user must type the alias exactly. Case mismatch is not a confirmation."""
    p = _create_person(db_session, alias="Alice")
    resp = authed_client.post(f"/people/{p.id}/delete", data={"confirm_alias": "alice"})
    assert resp.status_code == 400


def test_delete_person_with_wrong_alias_still_shows_session_list(authed_client, db_session):
    """Regression: destroy rerender must include sessions so the list still renders."""
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-04-15", ratings={"energy": 4}, notes="kept", link_urls=[])
    db_session.commit()

    resp = authed_client.post(f"/people/{p.id}/delete", data={"confirm_alias": "WRONG"})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    # The session list must still render; "No sessions yet" should NOT appear
    assert "2026-04-15" in body
    assert "No sessions yet" not in body
