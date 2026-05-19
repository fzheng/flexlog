"""Unit tests for the security-headers after_request hook.

Verifies the headers the registered hook produces. The integration
test (test_security_headers_applied.py) verifies the same headers
land on real HTTP responses."""
from __future__ import annotations


def test_headers_dict_keys():
    """The module exposes a _SECURITY_HEADERS dict with the 5 expected
    headers."""
    from flexlog.web.security_headers import _SECURITY_HEADERS
    expected = {
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    }
    assert set(_SECURITY_HEADERS.keys()) == expected


def test_csp_blocks_inline_script():
    """The CSP must NOT include 'unsafe-inline' in script-src — flexlog
    has no inline <script> blocks and this prevents an XSS from running
    even if user input slips past the autoescape."""
    from flexlog.web.security_headers import _SECURITY_HEADERS
    csp = _SECURITY_HEADERS["Content-Security-Policy"]
    # script-src directive must not contain unsafe-inline
    # (style-src is allowed to keep 'unsafe-inline' for template
    # inline-style attributes; that's documented separately.)
    assert "script-src" in csp
    # Extract the script-src directive
    parts = [p.strip() for p in csp.split(";")]
    script_src_parts = [p for p in parts if p.startswith("script-src")]
    assert script_src_parts, "CSP missing script-src directive"
    assert "'unsafe-inline'" not in script_src_parts[0], (
        f"script-src must not allow unsafe-inline: {script_src_parts[0]}"
    )


def test_csp_blocks_external_connect():
    """connect-src 'self' — XHR/fetch only to flexlog. Blocks a
    compromised vendored JS from exfiltrating to an attacker host."""
    from flexlog.web.security_headers import _SECURITY_HEADERS
    csp = _SECURITY_HEADERS["Content-Security-Policy"]
    assert "connect-src 'self'" in csp


def test_csp_blocks_framing():
    """frame-ancestors 'none' — clickjacking protection."""
    from flexlog.web.security_headers import _SECURITY_HEADERS
    csp = _SECURITY_HEADERS["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp


def test_x_frame_options_deny():
    from flexlog.web.security_headers import _SECURITY_HEADERS
    assert _SECURITY_HEADERS["X-Frame-Options"] == "DENY"


def test_x_content_type_options_nosniff():
    from flexlog.web.security_headers import _SECURITY_HEADERS
    assert _SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"


def test_referrer_policy_no_referrer():
    from flexlog.web.security_headers import _SECURITY_HEADERS
    assert _SECURITY_HEADERS["Referrer-Policy"] == "no-referrer"


def test_permissions_policy_denies_hardware():
    from flexlog.web.security_headers import _SECURITY_HEADERS
    pp = _SECURITY_HEADERS["Permissions-Policy"]
    for feature in ("geolocation", "camera", "microphone"):
        assert f"{feature}=()" in pp, f"Permissions-Policy missing {feature}=()"


def test_register_security_headers_attaches_after_request_hook():
    """register_security_headers(app) must install an after_request
    hook that mutates the outgoing response. Use a minimal Flask app
    to verify."""
    from flask import Flask
    from flexlog.web.security_headers import (
        _SECURITY_HEADERS, register_security_headers,
    )

    app = Flask(__name__)

    @app.route("/__hello")
    def _hello():
        return "hi"

    register_security_headers(app)
    client = app.test_client()
    resp = client.get("/__hello")
    for name, expected in _SECURITY_HEADERS.items():
        assert resp.headers.get(name) == expected, (
            f"missing or wrong {name}: got {resp.headers.get(name)!r}, "
            f"expected {expected!r}"
        )
