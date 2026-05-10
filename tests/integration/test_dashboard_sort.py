"""Dashboard sort options end-to-end."""
from __future__ import annotations


def _create(client, alias):
    resp = client.post("/people", data={"alias": alias, "tags": ""})
    assert resp.status_code in (302, 303)


def test_default_sort_is_alias(client, db_session):
    _create(client, "charlie")
    _create(client, "alice")
    _create(client, "Bob")
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    a = body.find("alice")
    b = body.find("Bob")
    c = body.find("charlie")
    assert 0 < a < b < c


def test_sort_by_session_count(client, db_session):
    from flexlog.db.models import Person
    _create(client, "Many")
    _create(client, "Few")
    db_session.expire_all()
    many = db_session.query(Person).filter_by(alias="Many").one()
    few = db_session.query(Person).filter_by(alias="Few").one()
    for d in ("2026-01-01", "2026-01-02", "2026-01-03"):
        client.post(
            f"/people/{many.id}/sessions",
            data={"session_date": d, "overall_score": 3, "notes": ""},
        )
    client.post(
        f"/people/{few.id}/sessions",
        data={"session_date": "2026-01-01", "overall_score": 3, "notes": ""},
    )
    db_session.expire_all()
    resp = client.get("/?sort=session_count")
    body = resp.get_data(as_text=True)
    assert body.find("Many") < body.find("Few")


def test_sort_select_renders_with_options(client, db_session):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert 'name="sort"' in body
    for v in ("alias", "last_date", "session_count", "avg_score"):
        assert f'value="{v}"' in body
