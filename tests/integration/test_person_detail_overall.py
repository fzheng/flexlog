"""Person detail shows 'Average across N sessions: X.X' above the
session list, and each session row shows its own overall."""
from __future__ import annotations


def test_person_detail_shows_average(authed_client, person, db_session):
    from flexlog.services.sessions import create_session
    create_session(db_session, person_id=person.id, session_date="2026-01-01",
                   ratings={"energy": 4}, notes=None, link_urls=[])
    create_session(db_session, person_id=person.id, session_date="2026-01-02",
                   ratings={"energy": 5}, notes=None, link_urls=[])
    db_session.commit()

    body = authed_client.get(f"/people/{person.id}").get_data(as_text=True)
    # Average of 4 and 5 is 4.5
    assert "4.5" in body
    assert "2" in body  # N
    # The summary line wording (configurable via UI string)
    assert "average" in body.lower() or "avg" in body.lower()


def test_person_detail_no_sessions_hides_average(authed_client, person, db_session):
    body = authed_client.get(f"/people/{person.id}").get_data(as_text=True)
    # Confirm the page renders at all
    assert person.alias in body
    # No "Average across" wording when there are no sessions
    assert "Average across" not in body


def test_session_row_shows_overall(authed_client, person, db_session):
    from flexlog.services.sessions import create_session
    create_session(db_session, person_id=person.id, session_date="2026-01-01",
                   ratings={"energy": 3}, notes="hello", link_urls=[])
    db_session.commit()

    body = authed_client.get(f"/people/{person.id}").get_data(as_text=True)
    # Locate the session-row HTML block and confirm overall appears inside it.
    import re
    m = re.search(r'<li class="session-row".*?</li>', body, re.DOTALL)
    assert m is not None, "no session-row block found"
    assert "3.0" in m.group(0)
