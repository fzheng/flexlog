"""Dashboard route (root /).

Replaces the M1 placeholder home_bp. The Flask blueprint endpoint name is
deliberately set to "home" (not "dashboard") so existing
url_for("home.home") calls in templates and redirects continue to work
unchanged. Renaming the endpoint would mean editing every caller — not
worth it for an internal-only string.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from flexlog.db import get_db
from flexlog.services.people import search_people

# Endpoint name MUST stay "home" to preserve url_for("home.home") calls
# in M1's existing templates and Task 10's destroy redirect.
dashboard_bp = Blueprint("home", __name__)


@dashboard_bp.get("/")
def home():
    query = request.args.get("q", "").strip()
    people = search_people(get_db(), query)
    return render_template("dashboard.html", people=people, query=query)
