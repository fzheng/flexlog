"""ProxyFix wrap + Secure cookie behavior gated on FLEXLOG_BEHIND_TLS=1."""
from __future__ import annotations

import pytest


def test_no_proxy_fix_in_dev_default(app):
    """Without FLEXLOG_BEHIND_TLS=1, the wsgi_app is NOT wrapped in
    ProxyFix — we don't want dev tools talking to localhost to trust
    spoofed X-Forwarded headers."""
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert not isinstance(app.wsgi_app, ProxyFix)


def test_session_cookie_not_secure_in_dev_default(app):
    """Same gate — SESSION_COOKIE_SECURE stays False so the dev
    server (HTTP) can set cookies."""
    assert app.config.get("SESSION_COOKIE_SECURE") is not True


def test_proxy_fix_installed_when_behind_tls(monkeypatch, tmp_data_dir):
    """With FLEXLOG_BEHIND_TLS=1 set, create_app wraps wsgi_app in
    ProxyFix and forces SESSION_COOKIE_SECURE=True."""
    monkeypatch.setenv("FLEXLOG_BEHIND_TLS", "1")
    from flexlog.app import create_app
    from werkzeug.middleware.proxy_fix import ProxyFix
    new_app = create_app()
    new_app.config["TESTING"] = True
    new_app.config["WTF_CSRF_ENABLED"] = False
    assert isinstance(new_app.wsgi_app, ProxyFix)
    assert new_app.config.get("SESSION_COOKIE_SECURE") is True


def test_install_proxy_fix_is_idempotent(app, monkeypatch):
    """install_proxy_fix can be called twice without double-wrapping."""
    from flexlog.web.proxy_fix import install_proxy_fix
    from werkzeug.middleware.proxy_fix import ProxyFix

    install_proxy_fix(app)
    inner1 = app.wsgi_app
    assert isinstance(inner1, ProxyFix)

    install_proxy_fix(app)
    inner2 = app.wsgi_app
    assert inner1 is inner2  # not re-wrapped
