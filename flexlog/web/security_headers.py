"""Inject security response headers on every HTTP response.

Wired into create_app() via register_security_headers(app). Sends
the same headers on every response (authed or not, success or
error) — no exemption paths, so a forgotten error handler can't
slip through without protection.

Header rationale, briefly:

- CSP default-src 'self' blocks fetching arbitrary external
  resources. script-src 'self' (no 'unsafe-inline') means even if
  user input reaches the DOM, an attacker can't execute it as a
  script. connect-src 'self' blocks exfiltration to attacker hosts
  via XHR/fetch — the most important defense against a compromised
  vendored JS file. img-src adds 'data:' for the avatar cropper's
  data-URL preview; style-src keeps 'unsafe-inline' because some
  templates use inline style="..." attributes (tracked for a future
  CSS audit pass; not blocking here).
- X-Frame-Options: DENY is a legacy backup for frame-ancestors 'none'.
- X-Content-Type-Options: nosniff blocks browsers from MIME-sniffing
  a misdeclared response.
- Referrer-Policy: same-origin — external sites we link to (link
  thumbnails, fake-Google redirect, etc.) get no Referer header at
  all. But same-origin navigations + form POSTs DO include the
  Referer so Flask-WTF's strict-HTTPS CSRF check can validate it.
  Using "no-referrer" globally breaks form submission on HTTPS:
  Flask-WTF returns 400 "Bad Request - The referrer header is
  missing" because the browser obeys the policy on our own forms too.
- Permissions-Policy explicitly denies hardware APIs flexlog never
  uses, so a compromised script can't ask the user for them.
"""
from __future__ import annotations

import os

from flask import Flask, Response


_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    # form-action covers the entire redirect chain, not just the initial
    # POST target. The fake-Google landing page intentionally 303-redirects
    # non-password input to google.com/search, so we have to allow it
    # explicitly here. Without google.com, the browser blocks the
    # redirect with "Sending form data violates form-action 'self'."
    "form-action 'self' https://www.google.com"
)

_PERMISSIONS_POLICY = (
    "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
)

_SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": _PERMISSIONS_POLICY,
}

# HSTS: pin browsers to HTTPS for a year, including all subdomains. Only
# emitted when FLEXLOG_BEHIND_TLS=1 — in dev (HTTP loopback) emitting it
# would brick localhost browsing for a year.
_HSTS = "max-age=31536000; includeSubDomains"


def register_security_headers(app: Flask) -> None:
    """Install an after_request hook that adds the security headers
    in _SECURITY_HEADERS to every response. When FLEXLOG_BEHIND_TLS=1
    is set, also emit Strict-Transport-Security."""
    behind_tls = os.environ.get("FLEXLOG_BEHIND_TLS") == "1"

    @app.after_request
    def _add_security_headers(response: Response) -> Response:
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if behind_tls:
            response.headers.setdefault("Strict-Transport-Security", _HSTS)
        return response
