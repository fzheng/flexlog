def test_person_detail_no_sessions_shows_empty_state(authed_client, db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    resp = authed_client.get(f"/people/{p.id}")
    body = resp.get_data(as_text=True)
    assert "No sessions yet" in body
    assert f"/people/{p.id}/sessions/new" in body  # Add Session button wired


def test_person_detail_lists_sessions_newest_first(authed_client, db_session):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-03-01", ratings={"energy": 3}, notes="oldest", link_urls=[])
    create_session(db_session, person_id=p.id, session_date="2026-05-01", ratings={"energy": 5}, notes="newest", link_urls=[])
    create_session(db_session, person_id=p.id, session_date="2026-04-01", ratings={"energy": 4}, notes="middle", link_urls=[])
    db_session.commit()

    resp = authed_client.get(f"/people/{p.id}")
    body = resp.get_data(as_text=True)
    # All three dates appear
    assert "2026-03-01" in body
    assert "2026-04-01" in body
    assert "2026-05-01" in body
    # Order: newest first → 2026-05-01 appears before 2026-03-01 in the body
    pos_newest = body.find("2026-05-01")
    pos_oldest = body.find("2026-03-01")
    assert pos_newest < pos_oldest
    # Notes preview shows
    assert "newest" in body


def test_person_detail_session_card_links_to_session_detail(authed_client, db_session):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", ratings={"energy": 4}, notes=None, link_urls=[])
    db_session.commit()
    resp = authed_client.get(f"/people/{p.id}")
    assert f"/sessions/{s.id}" in resp.get_data(as_text=True)


def test_person_detail_session_card_link_count(authed_client, db_session):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(
        db_session, person_id=p.id, session_date="2026-04-15",
        ratings={"energy": 4}, notes=None,
        link_urls=["https://a.com", "https://b.com"],
    )
    db_session.commit()
    resp = authed_client.get(f"/people/{p.id}")
    body = resp.get_data(as_text=True)
    assert "2 link" in body  # "2 links"
