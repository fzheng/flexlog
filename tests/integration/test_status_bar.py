"""End-to-end: the status bar is rendered on authed pages, hidden
on unauthed pages, and reflects current storage + last session save.

NOTE: these tests will FAIL until Task 8 of the v0.8.0 status-bar plan
adds the template partial + CSS. The wiring (context processor +
filters) lands in Task 7; the markup lands in Task 8.
"""
from __future__ import annotations


def test_status_bar_rendered_on_authed_dashboard(authed_client):
    body = authed_client.get("/dashboard").get_data(as_text=True)
    assert 'class="status-bar"' in body, \
        "status-bar partial not rendered on dashboard"
    assert "used" in body  # "X.Y GB used" / "12 KB used"


def test_status_bar_says_no_sessions_when_empty(authed_client):
    body = authed_client.get("/dashboard").get_data(as_text=True)
    assert "No sessions yet" in body


def test_status_bar_shows_last_session_after_create(
    authed_client, person, db_session,
):
    from flexlog.services.sessions import create_session
    create_session(
        db_session,
        person_id=person.id,
        session_date="2026-05-18",
        ratings={"energy": 4},
        notes=None,
        link_urls=[],
        link_thumb_keys=[],
    )
    db_session.commit()
    body = authed_client.get("/dashboard").get_data(as_text=True)
    assert "Last session:" in body
    assert "No sessions yet" not in body


def test_status_bar_not_rendered_on_landing(client):
    """Unauthed landing page must not show the bar (and shouldn't try
    to query the DB — there's no engine attached)."""
    body = client.get("/").get_data(as_text=True)
    assert 'class="status-bar"' not in body
