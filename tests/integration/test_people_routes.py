def _post(authed_client, url, data):
    return authed_client.post(url, data=data, follow_redirects=False)


def test_get_new_person_form_renders(authed_client):
    resp = authed_client.get("/people/new")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Alias" in body
    assert "Tags" in body
    # Comes from BUILTIN_UI_DEFAULTS
    assert "Save" in body


def test_post_create_person_minimal(authed_client):
    resp = _post(authed_client, "/people", {"alias": "Alice", "tags": ""})
    assert resp.status_code == 302  # redirect to detail page
    assert "/people/" in resp.headers["Location"]


def test_post_create_person_with_tags(authed_client, db_session):
    from flexlog.db.models import Person

    _post(authed_client, "/people", {"alias": "Alice", "tags": "Engineer, Friend"})
    p = db_session.query(Person).filter_by(alias="Alice").one()
    assert sorted(t.name for t in p.tags) == ["Engineer", "Friend"]


def test_post_create_person_empty_alias_rerenders_form(authed_client):
    resp = authed_client.post("/people", data={"alias": "", "tags": ""})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "alias" in body.lower()


def test_get_edit_person_form_prefills(authed_client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="Engineer, Friend")
    db_session.commit()
    resp = authed_client.get(f"/people/{p.id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Alice" in body
    # Tag input should pre-populate with display names
    assert "Engineer" in body
    assert "Friend" in body


def test_get_edit_person_404_when_missing(authed_client):
    resp = authed_client.get("/people/no-such-id/edit")
    assert resp.status_code == 404


def test_post_update_person(authed_client, db_session):
    from flexlog.services.people import create_person, get_person

    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    resp = _post(authed_client, f"/people/{p.id}", {"alias": "Alicia", "tags": "Coach"})
    assert resp.status_code == 302
    refreshed = get_person(db_session, p.id)
    db_session.refresh(refreshed)
    assert refreshed.alias == "Alicia"
    assert [t.name for t in refreshed.tags] == ["Coach"]


def test_post_update_person_404_when_missing(authed_client):
    resp = authed_client.post("/people/no-such-id", data={"alias": "X", "tags": ""})
    assert resp.status_code == 404


def test_post_update_person_empty_alias_rerenders_form(authed_client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    resp = authed_client.post(f"/people/{p.id}", data={"alias": "", "tags": ""})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "alias" in body.lower()


def test_xss_in_alias_is_escaped(authed_client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="<script>alert(1)</script>", tag_input="")
    db_session.commit()
    resp = authed_client.get(f"/people/{p.id}/edit")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_xss_in_tag_name_is_escaped(authed_client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="<img onerror=x>")
    db_session.commit()
    resp = authed_client.get(f"/people/{p.id}/edit")
    body = resp.get_data(as_text=True)
    assert "<img onerror=x>" not in body


def test_get_person_detail(authed_client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="Friend, Engineer")
    db_session.commit()
    resp = authed_client.get(f"/people/{p.id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Alias is rendered
    assert "Alice" in body
    # Tag chips render
    assert "Friend" in body
    assert "Engineer" in body
    # Empty session list copy from BUILTIN_UI_DEFAULTS
    assert "No sessions yet" in body
    # Edit link present
    assert f"/people/{p.id}/edit" in body
    # Delete link/form present
    assert f"/people/{p.id}/delete" in body


def test_get_person_detail_404(authed_client):
    resp = authed_client.get("/people/no-such-id")
    assert resp.status_code == 404


def test_person_new_form_includes_avatar_cropper(authed_client):
    resp = authed_client.get("/people/new")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'id="avatar-file"' in body
    assert 'name="avatar_blob"' in body
    assert 'enctype="multipart/form-data"' in body
    assert "cropper.min.js" in body
    assert "avatar_cropper.js" in body


def test_avatar_blob_input_is_hidden(authed_client):
    """Regression: avatar_blob is a HiddenField, not a StringField. Browsers
    must not render an empty visible text box below the cropper area."""
    import re
    resp = authed_client.get("/people/new")
    body = resp.get_data(as_text=True)
    m = re.search(r'<input[^>]*\bname="avatar_blob"[^>]*>', body)
    assert m, "avatar_blob input not found"
    assert 'type="hidden"' in m.group(0), (
        f"avatar_blob input should be type=hidden, got: {m.group(0)}"
    )
