"""Error pages render the friendly templates, not raw werkzeug HTML."""
from __future__ import annotations


def test_404_returns_rendered_template(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "Page not found" in body
    # Site chrome (header + nav) appears — confirms it extends _base.html.
    assert "site-header" in body or "site-nav" in body


def test_413_returns_rendered_template(tmp_data_dir):
    """Send a request body larger than MAX_CONTENT_LENGTH — Flask returns 413
    automatically. Build a fresh app with a tiny cap so we don't need 3 GiB.
    """
    from flexlog.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["MAX_CONTENT_LENGTH"] = 10  # tiny cap, forces 413

    test_client = app.test_client()
    resp = test_client.post(
        "/people",
        data="x" * 100,
        content_type="application/octet-stream",
    )
    assert resp.status_code == 413
    assert "Upload too large" in resp.get_data(as_text=True)
