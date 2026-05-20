"""Wraps werkzeug's ProxyFix for Railway's single-proxy-hop deployment.

Railway terminates TLS and forwards requests to our container with
X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host set. The single
hop means we trust exactly ONE proxy. Wrong hop count is a real risk:
trusting too many lets a client spoof X-Forwarded-For headers."""
from __future__ import annotations

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix


def install_proxy_fix(app: Flask) -> None:
    """Wrap app.wsgi_app with ProxyFix. Idempotent — calling twice
    only adds the middleware once."""
    if getattr(app, "_proxy_fix_installed", False):
        return
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app._proxy_fix_installed = True
