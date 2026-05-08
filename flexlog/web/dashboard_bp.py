"""Dashboard route (root /)."""

from __future__ import annotations

from flask import Blueprint, render_template, request

from flexlog.db import get_db
from flexlog.services.people import list_dashboard_rows

dashboard_bp = Blueprint("home", __name__)


@dashboard_bp.get("/")
def home():
    query = request.args.get("q", "").strip()
    rows = list_dashboard_rows(get_db(), query)
    return render_template("dashboard.html", rows=rows, query=query)
