"""/robots.txt + landing noindex meta."""
from __future__ import annotations


def test_robots_txt_disallows_all(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    assert "Disallow: /" in body
    assert "User-agent: *" in body


def test_landing_has_noindex_meta(client):
    body = client.get("/").get_data(as_text=True)
    assert 'name="robots"' in body
    assert "noindex" in body
