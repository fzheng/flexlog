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


def test_form_renders_star_inputs(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    # Star buttons rendered for the energy dim
    assert 'data-dim-id="energy"' in body
    assert 'name="rating_energy"' in body  # hidden mirror input
    assert 'class="star"' in body
    # Five star buttons per dim
    assert body.count('data-value="1"') >= 1
    assert body.count('data-value="5"') >= 1


def test_form_submit_with_star_value_stores_int(csrf_authed_client, csrf_person):
    """The form posts rating_<id>=N (integer) just like the old number
    input; server stores it in ratings_json as int N."""
    import re
    person = csrf_person
    body = csrf_authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    token = m.group(1)

    resp = csrf_authed_client.post(
        f"/people/{person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "2026-05-17",
            "rating_energy": "3",
            "notes": "",
            "link_urls": [],
        },
    )
    assert resp.status_code == 302  # redirect to detail
    # Detail page renders the stored value
    detail_body = csrf_authed_client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "★★★☆☆" in detail_body  # 3 stars
    assert "3.0" in detail_body  # overall (single dim, weight 1.0)


def test_rating_stars_js_is_served(authed_client):
    resp = authed_client.get("/static/js/rating_stars.js")
    assert resp.status_code == 200
    assert b"rating_stars" in resp.data or b"star" in resp.data


def test_server_clamps_out_of_range_rating(csrf_authed_client, csrf_person):
    """If JS is bypassed and someone POSTs rating_<id>=99, the server
    silently clamps to 5 rather than erroring."""
    import re
    person = csrf_person
    body = csrf_authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)

    resp = csrf_authed_client.post(
        f"/people/{person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "2026-05-17",
            "rating_energy": "99",  # out of range
            "notes": "",
        },
    )
    assert resp.status_code == 302
    detail_body = csrf_authed_client.get(resp.headers["Location"]).get_data(as_text=True)
    # Clamped to 5
    assert "★★★★★" in detail_body
    assert "5.0" in detail_body  # overall
