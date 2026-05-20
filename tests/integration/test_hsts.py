"""HSTS header presence is gated on FLEXLOG_BEHIND_TLS=1."""
from __future__ import annotations


def test_hsts_absent_when_not_behind_tls(authed_client):
    """Dev / local: no HSTS (we're served over HTTP)."""
    resp = authed_client.get("/dashboard")
    assert "Strict-Transport-Security" not in resp.headers


def test_hsts_present_when_behind_tls(monkeypatch, tmp_data_dir):
    """Prod: HSTS header present with max-age 1 year + subdomains."""
    monkeypatch.setenv("FLEXLOG_BEHIND_TLS", "1")
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.get("/")
    assert "Strict-Transport-Security" in resp.headers
    hsts = resp.headers["Strict-Transport-Security"]
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
