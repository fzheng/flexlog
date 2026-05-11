"""Flask application factory for flexlog."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, current_app, redirect, request, session, url_for
from flask_wtf.csrf import CSRFProtect

from flexlog import paths
from flexlog.auth import ALLOWED_UNAUTH_ENDPOINTS, is_authed
from flexlog.config_loader import Config, load_or_bootstrap
from flexlog.db import Base, register_db_teardown  # engine attached post-login
from flexlog.secret_key import load_or_create_secret_key
from flexlog.services.auth import bootstrap_state
from flexlog.web import register_blueprints
from flexlog.web.filters import build_labels_context, notes_preview, ui_filter

LOGGER_NAME = "flexlog"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def create_app() -> Flask:
    _configure_logging()

    data_dir = paths.data_dir()
    paths.ensure_layout()

    # Tmp-uploads sweep (unchanged from v0.1.0)
    import time
    tmp_dir = paths.tmp_uploads_dir()
    cutoff = time.time() - 3600
    if tmp_dir.exists():
        for entry in tmp_dir.iterdir():
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink(missing_ok=True)
            except OSError:
                pass

    config: Config = load_or_bootstrap(paths.config_path())
    loaded_at = datetime.now(timezone.utc)
    secret_key = load_or_create_secret_key(data_dir / ".secret_key")

    app = Flask(
        "flexlog",
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["FLEXLOG"] = config
    app.config["FLEXLOG_LOADED_AT"] = loaded_at
    app.config["FLEXLOG_DATA_DIR"] = str(data_dir)
    app.config["SECRET_KEY"] = secret_key
    app.config["AUTH_EPOCH"] = secrets.token_hex(16)
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024 * 1024
    app.debug = os.environ.get("FLEXLOG_DEBUG", "") == "1"

    CSRFProtect(app)

    # NOTE: No DB engine at boot. attach_engine_at_runtime is called from
    # landing_bp.submit after the master key is unwrapped. The session-
    # close teardown is registered here, before any engine attach, so it
    # fires for every request — including the post-login ones whose engine
    # was attached at runtime via attach_engine_at_runtime (which does NOT
    # itself register a teardown).
    register_db_teardown(app)

    # Jinja filters + context processors (unchanged)
    from jinja2 import pass_context

    @pass_context
    def _ui(_ctx, key: str) -> str:
        return ui_filter(key)

    app.jinja_env.filters["ui"] = _ui
    app.jinja_env.filters["notes_preview"] = notes_preview

    @app.context_processor
    def _inject_labels() -> dict[str, object]:
        return {"labels": build_labels_context(current_app.config["FLEXLOG"])}

    @app.context_processor
    def _inject_auth_state() -> dict[str, object]:
        authed = bool(
            session.get("authed")
            and session.get("epoch") == current_app.config.get("AUTH_EPOCH")
        )
        return {"is_authed": authed}

    app.url_map.merge_slashes = False

    register_blueprints(app)

    # Auth + bootstrap gate
    @app.before_request
    def _gate():
        endpoint = request.endpoint or ""
        # Allowlist (no auth, no bootstrap check needed)
        if endpoint in ALLOWED_UNAUTH_ENDPOINTS:
            return None
        # Setup endpoints (no auth, but pre-DB)
        if endpoint.startswith("setup."):
            return None
        # All other endpoints: must be authed
        if is_authed(session, app.config):
            return None
        return redirect(url_for("landing.index"), code=303)

    # Error handlers (unchanged)
    from flask import render_template as _render_template

    @app.errorhandler(404)
    def _not_found(_e):
        return _render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def _too_large(_e):
        return _render_template("errors/413.html"), 413

    @app.errorhandler(500)
    def _server_error(_e):
        return _render_template("errors/500.html"), 500

    return app


def _configure_logging() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
