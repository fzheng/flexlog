"""Logout endpoint."""
from __future__ import annotations

from flask import Blueprint, current_app, redirect, session, url_for

from flexlog.auth import mark_unauthed
from flexlog.db import detach_engine_at_runtime

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/logout")
def logout():
    mark_unauthed(session)
    # Defense in depth: drop the master key + dispose the encrypted
    # DB engine from process memory. Python doesn't zero memory so a
    # cold-boot capture of the process could still recover the key
    # from freed heap, but at minimum: any future request that
    # bypasses the auth gate (a hypothetical bug in
    # ALLOWED_UNAUTH_ENDPOINTS) can no longer read user data via
    # get_db() — there's nothing attached.
    current_app.config.pop("MASTER_KEY", None)
    detach_engine_at_runtime(current_app._get_current_object())
    return redirect(url_for("landing.index"), code=303)
