"""Placeholder home/dashboard route for M1.

In M2 this is replaced by the real people-list dashboard. M1 keeps just
enough to verify the app factory wires up config-driven labels correctly.
"""

from __future__ import annotations

from flask import Blueprint, render_template

home_bp = Blueprint("home", __name__)


@home_bp.get("/")
def home():
    return render_template("home.html")
