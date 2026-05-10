"""Fake Google-clone landing page + search-or-login handler.

GET  /  -> if authed, 303 -> /dashboard
       -> else,        render landing/index.html
POST /  -> if SHA-512(q) matches admin hash: log in + 303 -> /dashboard
       -> else:                              303 -> google.com/search?q=q

The two views share the same URL; the GET handler is named `index` and
the POST handler is named `submit` so the auth allowlist can target each
endpoint by name.
"""
from __future__ import annotations

from urllib.parse import urlencode

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from flexlog.auth import is_authed, mark_authed, verify_password

landing_bp = Blueprint("landing", __name__)


@landing_bp.get("/")
def index():
    if is_authed(session, current_app.config):
        # Authed users get the real dashboard at / (no extra redirect hop).
        # Importing here avoids a circular import at module load time.
        from flexlog.web.dashboard_bp import home as dashboard_home
        return dashboard_home()
    brand = current_app.config["FLEXLOG"].app.name
    return render_template("landing/index.html", brand=brand)


@landing_bp.post("/")
def submit():
    typed = request.form.get("q", "")
    if not typed:
        # Empty submission — re-render the fake page rather than redirect
        # to https://www.google.com/search?q= (which would look weird).
        brand = current_app.config["FLEXLOG"].app.name
        return render_template("landing/index.html", brand=brand)

    expected = current_app.config["ADMIN_PASSWORD_HASH"]
    if verify_password(typed, expected):
        mark_authed(session, current_app.config)
        # Redirect to / which (now authed) renders the dashboard inline.
        return redirect(url_for("landing.index"), code=303)

    # Wrong password — redirect to a real Google search for the typed term
    # so the page acts like a vanity redirect to anyone who didn't know
    # the password.
    return redirect(
        "https://www.google.com/search?" + urlencode({"q": typed}),
        code=303,
    )
