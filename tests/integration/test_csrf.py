"""CSRF integration tests — verify that Flask-WTF rejects POST requests
that arrive without a valid CSRF token when the protection is enabled."""

from __future__ import annotations


def test_post_create_person_without_csrf_rejected(csrf_authed_client):
    """With CSRF enabled, a POST without a valid token must be rejected."""
    resp = csrf_authed_client.post("/people", data={"alias": "Alice", "tags": ""})
    # Flask-WTF returns 400 (or 403 depending on config) on CSRF failure
    assert resp.status_code in (400, 403)


def test_post_delete_person_without_csrf_rejected(csrf_authed_client, csrf_app):
    """Even DELETE-on-POST routes need CSRF."""
    # We need a valid person id first. Create one inside the csrf_app context.
    from flexlog.db import close_db, get_db
    from flexlog.services.people import create_person

    with csrf_app.app_context():
        db = get_db()
        p = create_person(db, alias="Alice", tag_input="")
        db.commit()
        pid = p.id
        close_db()

    resp = csrf_authed_client.post(f"/people/{pid}/delete", data={"confirm_alias": "Alice"})
    assert resp.status_code in (400, 403)
