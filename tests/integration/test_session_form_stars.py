"""Detail page renders the weighted overall + per-dim star rows."""
from __future__ import annotations


def test_detail_shows_overall_and_stars(authed_client, person, db_session):
    from flexlog.services.sessions import create_session

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes="hello", link_urls=[],
    )
    db_session.commit()

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    # Single-dim config: energy weight 1.0, value 4 → overall 4.0
    assert "4.0" in body
    assert "overall" in body.lower()
    # Star rendering: 4 filled + 1 empty
    assert "★★★★☆" in body
