"""Inject security response headers on every HTTP response.

Wired into create_app() via register_security_headers(app). Sends
the same headers on every response (authed or not, success or
error) — no exemption paths, so a forgotten error handler can't
slip through without protection.

Header rationale, briefly:

- CSP — see the inline audit table above _CSP below for the
  per-directive rationale and which feature each token serves.
  Whenever you add a feature that loads anything from a non-self
  origin (or uses a new URL scheme like blob:/filesystem:/etc.),
  check the audit, update it, and update the matching directive
  in the same commit. The CSP is enforced strictly — silent
  blocking of legitimate features is the failure mode.
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


# CSP audit (every directive mapped to actual feature use, May 2026):
#
# default-src 'self'  → fallback for media-src, font-src, worker-src, etc.
#   Used by: <audio src="/media/...">, <video src="/media/...">,
#   system fonts (no external @font-face). All same-origin.
#
# script-src 'self'   → vendored JS (PhotoSwipe, Cropper.js, custom)
#   under /static/. No inline <script>, no eval, no inline on*=
#   handlers (tripwire test enforces). No CDN.
#
# img-src 'self' data: blob:
#   - 'self'  → /media/<file_key>, /static/...
#   - data:   → avatar cropper writes the cropped result as a
#             data:image/jpeg;base64 URL into <img.src> for preview
#             before form submit (avatar_cropper.js:64).
#   - blob:   → avatar cropper feeds the SELECTED file into a hidden
#             <img> via URL.createObjectURL(file) so Cropper.js can
#             measure it (avatar_cropper.js:36). Without `blob:` the
#             browser blocks this with "Loading the image 'blob:...'
#             violates img-src 'self' data:".
#
# style-src 'self' 'unsafe-inline'
#   'unsafe-inline' is kept because some templates use style="..."
#   attributes (avatar cropper sizing, ARIA helpers, link-thumb
#   placeholders). Tightening requires a CSS audit pass — not
#   blocking. Note: 'unsafe-inline' on style is materially less
#   dangerous than on script.
#
# connect-src 'self'
#   /sessions/upload (XHR + fetch), /sessions/upload/<key> (DELETE),
#   any future internal AJAX. No external API calls — the running
#   app makes zero outbound HTTP (asserted by qa_checklist test).
#
# frame-ancestors 'none'  → flexlog cannot be embedded in an iframe
#   from any origin. Prevents clickjacking.
#
# base-uri 'self'  → <base href="..."> can only point at our origin.
#   Defense-in-depth against XSS injecting a <base> to relocate
#   relative URLs to an attacker host.
#
# form-action 'self' https://www.google.com
#   CSP form-action enforces the entire redirect chain. The fake-
#   Google landing page POSTs to / and the handler 303s non-password
#   queries to google.com/search?q=... — that off-site destination
#   has to be allowlisted explicitly. Without it the browser blocks
#   the redirect with "Sending form data violates form-action 'self'".
#
# Directives we DON'T set (fall back to default-src 'self'):
#   object-src, media-src, worker-src, manifest-src, child-src — all
#   fine as same-origin-only. font-src — fine, no external fonts.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
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
