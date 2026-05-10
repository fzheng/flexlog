"""Logout endpoint."""
from __future__ import annotations

from flask import Blueprint, redirect, session, url_for

from flexlog.auth import mark_unauthed

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/logout")
def logout():
    mark_unauthed(session)
    return redirect(url_for("landing.index"), code=303)
