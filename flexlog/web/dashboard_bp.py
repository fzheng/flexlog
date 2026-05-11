"""Dashboard route (root /)."""

from __future__ import annotations

from flask import Blueprint, current_app, render_template, request

from flexlog.db import get_db
from flexlog.services.people import list_dashboard_rows

dashboard_bp = Blueprint("home", __name__)


@dashboard_bp.get("/dashboard")
def home():
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "alias").strip() or "alias"
    rows = list_dashboard_rows(get_db(), query, sort)
    cfg = current_app.config["FLEXLOG"]
    sortable_dimensions = [r for r in cfg.ratings if r.enabled and r.sortable]
    return render_template(
        "dashboard.html",
        rows=rows,
        query=query,
        sort=sort,
        sortable_dimensions=sortable_dimensions,
    )
