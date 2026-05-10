"""Flask application factory for flexlog."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, current_app
from flask_wtf.csrf import CSRFProtect

from flexlog import paths
from flexlog.config_loader import Config, load_or_bootstrap
from flexlog.db import Base, attach_to_app, make_engine, make_session_factory
from flexlog.secret_key import load_or_create_secret_key
from flexlog.web import register_blueprints
from flexlog.web.filters import build_labels_context, notes_preview, ui_filter

LOGGER_NAME = "flexlog"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def create_app() -> Flask:
    """Build and return the configured Flask app.

    Reads FLEXLOG_DATA_DIR (required), loads/bootstraps config.json, opens
    the SQLite database, and wires CSRF + DB lifecycle. Raises (DataDirError,
    ConfigError, SecretKeyError) on any startup failure. No fallback values
    — startup failures are loud and explicit.
    """
    _configure_logging()

    # 1. Validate data dir + create child layout
    data_dir = paths.data_dir()
    paths.ensure_layout()

    # Sweep stale uploads/.tmp/ files (>1 hour old) on startup per spec §4.3.
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

    # 2. Load (or bootstrap) config.json
    config: Config = load_or_bootstrap(paths.config_path())
    loaded_at = datetime.now(timezone.utc)

    # 3. Load or create the per-install secret key
    secret_key = load_or_create_secret_key(data_dir / ".secret_key")

    # 4. Build the Flask app
    app = Flask(
        "flexlog",
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["FLEXLOG"] = config
    app.config["FLEXLOG_LOADED_AT"] = loaded_at
    app.config["FLEXLOG_DATA_DIR"] = str(data_dir)
    app.config["SECRET_KEY"] = secret_key
    app.config["WTF_CSRF_ENABLED"] = True
    # Allow up to 3 GiB request body so 500 MB files × multiple uploads work.
    # Per-file size is enforced server-side in services/media.py.
    app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024 * 1024
    app.debug = os.environ.get("FLEXLOG_DEBUG", "") == "1"

    # 5. CSRF
    CSRFProtect(app)

    # 6. Database
    engine = make_engine(paths.db_path())
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    attach_to_app(app, engine, session_factory)

    # 7. Wire up filters + context processor
    app.jinja_env.filters["ui"] = lambda key: ui_filter(key)
    app.jinja_env.filters["notes_preview"] = notes_preview

    @app.context_processor
    def _inject_labels() -> dict[str, object]:
        # Read the live config on each render so a runtime reload picks up
        # entity/session label changes (not only ui_strings, which the `ui`
        # filter handles via current_app.config["FLEXLOG"]).
        return {"labels": build_labels_context(current_app.config["FLEXLOG"])}

    # Prevent Werkzeug from issuing 308 redirects for URLs with encoded slashes
    # (e.g. /media/%2Fetc%2Fpasswd). Without this, %2F gets decoded to / and
    # Werkzeug emits a permanent redirect to normalize double slashes before our
    # route handler can reject the path traversal attempt.
    app.url_map.merge_slashes = False

    # 8. Register blueprints
    register_blueprints(app)

    # 9. Register friendly error pages
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
    """Attach a stderr handler at INFO to the named flexlog logger.

    Idempotent — only attaches a handler once per process.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
