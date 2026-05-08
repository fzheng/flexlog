def _create_person(db_session, alias="Alice", tags=""):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def test_delete_person_with_correct_alias_succeeds(client, db_session):
    from flexlog.services.people import get_person

    p = _create_person(db_session, alias="Alice")
    resp = client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": "Alice"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    assert get_person(db_session, p.id) is None


def test_delete_person_with_wrong_alias_rerenders_with_error(client, db_session):
    from flexlog.services.people import get_person

    p = _create_person(db_session, alias="Alice")
    resp = client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": "Bob"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "alias" in body.lower()
    # Person must still exist
    assert get_person(db_session, p.id) is not None


def test_delete_person_with_empty_alias_rerenders_with_error(client, db_session):
    p = _create_person(db_session, alias="Alice")
    resp = client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": ""},
    )
    assert resp.status_code == 400


def test_delete_person_404_when_missing(client):
    resp = client.post("/people/no-such-id/delete", data={"confirm_alias": "X"})
    assert resp.status_code == 404


def test_delete_person_alias_check_is_case_sensitive(client, db_session):
    """The user must type the alias exactly. Case mismatch is not a confirmation."""
    p = _create_person(db_session, alias="Alice")
    resp = client.post(f"/people/{p.id}/delete", data={"confirm_alias": "alice"})
    assert resp.status_code == 400
