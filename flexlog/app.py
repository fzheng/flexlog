"""Flask application factory for flexlog."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, current_app, redirect, request, session, url_for
from flask_wtf.csrf import CSRFProtect

from flexlog import paths
from flexlog.auth import ALLOWED_UNAUTH_ENDPOINTS, is_authed, validate_admin_hash
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

    # 1b. Load .env from the data dir so FLEXLOG_ADMIN_PASSWORD_SHA512
    # is available before we validate it. python-dotenv's load_dotenv is
    # idempotent — repeated calls don't overwrite already-set vars unless
    # override=True (we leave override off so test monkeypatches win).
    env_path = data_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

    # 2. Load (or bootstrap) config.json
    config: Config = load_or_bootstrap(paths.config_path())
    loaded_at = datetime.now(timezone.utc)

    # 3. Load or create the per-install secret key
    secret_key = load_or_create_secret_key(data_dir / ".secret_key")

    # 3b. Validate the admin password hash (required).
    raw_hash = os.environ.get("FLEXLOG_ADMIN_PASSWORD_SHA512", "").strip()
    if not raw_hash:
        raise RuntimeError(
            "FLEXLOG_ADMIN_PASSWORD_SHA512 is not set. Generate the hash with "
            "`make hash-password` and add the line to "
            f"{env_path} (mode 0600 recommended)."
        )
    try:
        admin_hash = validate_admin_hash(raw_hash)
    except ValueError as e:
        raise RuntimeError(
            f"FLEXLOG_ADMIN_PASSWORD_SHA512 is invalid: {e}. "
            "Generate a fresh value with `make hash-password`."
        ) from e

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
    app.config["ADMIN_PASSWORD_HASH"] = admin_hash
    # AUTH_EPOCH is regenerated every process start. Cookies issued before
    # the restart no longer match → user is silently signed out.
    app.config["AUTH_EPOCH"] = secrets.token_hex(16)
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
    #
    # The `ui` filter is wrapped with @pass_context so Jinja2's compile-time
    # constant folding does NOT bake `{{ "key" | ui }}` calls into literals
    # on first render. Without this, runtime config reload would have no
    # effect on labels — the constant pool would hold pre-reload values
    # forever. See Jinja2's nodes._FilterTestCommon.as_const for the folding
    # logic that pass_context opts out of.
    from jinja2 import pass_context

    @pass_context
    def _ui(_ctx, key: str) -> str:
        return ui_filter(key)

    app.jinja_env.filters["ui"] = _ui
    app.jinja_env.filters["notes_preview"] = notes_preview

    @app.context_processor
    def _inject_labels() -> dict[str, object]:
        # Read the live config on each render so a runtime reload picks up
        # entity/session label changes (not only ui_strings, which the `ui`
        # filter handles via current_app.config["FLEXLOG"]).
        return {"labels": build_labels_context(current_app.config["FLEXLOG"])}

    @app.context_processor
    def _inject_auth_state() -> dict[str, object]:
        # Templates render the Logout button only when authed. We use the
        # raw session.get() here (not is_authed()) to avoid the side-effect
        # of refreshing last_seen during template rendering — auth status
        # for context-processor purposes is just "do we hold a valid auth
        # marker right now"; the actual gate runs in before_request.
        authed = bool(
            session.get("authed")
            and session.get("epoch") == current_app.config.get("AUTH_EPOCH")
        )
        return {"is_authed": authed}

    # Prevent Werkzeug from issuing 308 redirects for URLs with encoded slashes
    # (e.g. /media/%2Fetc%2Fpasswd). Without this, %2F gets decoded to / and
    # Werkzeug emits a permanent redirect to normalize double slashes before our
    # route handler can reject the path traversal attempt.
    app.url_map.merge_slashes = False

    # 8. Register blueprints
    register_blueprints(app)

    # 8b. Auth gate. Allowlist the landing endpoints and static; everything
    # else 303s to / when unauthed. Idle timeout is enforced by is_authed,
    # which also refreshes last_seen on success (sliding window).
    @app.before_request
    def _require_auth():
        endpoint = request.endpoint or ""
        if endpoint in ALLOWED_UNAUTH_ENDPOINTS:
            return None
        if is_authed(session, app.config):
            return None
        return redirect(url_for("landing.index"), code=303)

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
