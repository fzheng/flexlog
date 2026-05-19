"""End-to-end: every page response carries the 5 security headers."""
from __future__ import annotations


_EXPECTED_HEADERS = {
    "Content-Security-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
}


def _check_all_headers_present(resp):
    missing = _EXPECTED_HEADERS - set(resp.headers.keys())
    assert not missing, f"missing security headers: {missing}"


def test_landing_page_has_security_headers(client):
    resp = client.get("/")
    _check_all_headers_present(resp)


def test_dashboard_has_security_headers(authed_client):
    resp = authed_client.get("/dashboard")
    _check_all_headers_present(resp)


def test_static_file_has_security_headers(client):
    resp = client.get("/static/css/main.css")
    _check_all_headers_present(resp)


def test_404_has_security_headers(client):
    """Even 404 responses must carry the headers — an error page is
    rendered by the same app and must not regress security posture."""
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code in (404, 303)  # auth gate may redirect
    _check_all_headers_present(resp)


def test_csp_script_src_blocks_inline(authed_client):
    """The CSP returned to the browser must not whitelist inline
    scripts — verifies the production value, not just the unit
    module constant."""
    resp = authed_client.get("/dashboard")
    csp = resp.headers["Content-Security-Policy"]
    parts = [p.strip() for p in csp.split(";")]
    script_src = next(p for p in parts if p.startswith("script-src"))
    assert "'unsafe-inline'" not in script_src
