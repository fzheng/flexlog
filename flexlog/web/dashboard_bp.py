"""Dashboard route (root /)."""

from __future__ import annotations

from flask import Blueprint, render_template, request

from flexlog.db import get_db
from flexlog.services.people import list_dashboard_rows
from flexlog.services.sessions import enabled_rating_dimensions

dashboard_bp = Blueprint("home", __name__)


@dashboard_bp.get("/")
def home():
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "alias").strip() or "alias"
    rows = list_dashboard_rows(get_db(), query, sort)
    return render_template(
        "dashboard.html",
        rows=rows,
        query=query,
        sort=sort,
        rating_dimensions=enabled_rating_dimensions(),
    )
