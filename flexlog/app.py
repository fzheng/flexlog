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
from flexlog.web.filters import (
    build_labels_context,
    humanize_bytes_filter,
    iso_local_minute,
    notes_preview,
    ui_filter,
)

LOGGER_NAME = "flexlog"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

_TMP_SWEEP_CUTOFF_SECONDS = 86400  # 24h — slow uploads on slow disks
                                    # across an app restart shouldn't race
                                    # the sweep.


def _sweep_tmp_uploads() -> None:
    """Delete tmp-upload files older than _TMP_SWEEP_CUTOFF_SECONDS.
    Called at every app startup from create_app(). Best-effort —
    OSError on individual files is swallowed; the next startup tries
    again."""
    import time
    tmp_dir = paths.tmp_uploads_dir()
    if not tmp_dir.exists():
        return
    cutoff = time.time() - _TMP_SWEEP_CUTOFF_SECONDS
    for entry in tmp_dir.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
        except OSError:
            pass


def create_app() -> Flask:
    _configure_logging()

    data_dir = paths.data_dir()
    paths.ensure_layout()

    _sweep_tmp_uploads()

    # Cold-boot DB restore (Railway cloud deployment).
    # When FLEXLOG_STORAGE_BACKEND=s3 and the Volume's DB is missing,
    # pull the newest backup from the backup bucket so the app can
    # start serving immediately.
    _backup_storage = None
    if os.environ.get("FLEXLOG_STORAGE_BACKEND") == "s3":
        backup_bucket = os.environ.get("BACKUP_BUCKET")
        if backup_bucket:
            from flexlog.services.db_backup import restore_latest_if_missing
            from flexlog.storage.s3 import S3Storage
            _backup_storage = S3Storage(
                bucket=backup_bucket,
                endpoint_url=os.environ.get("BACKUP_ENDPOINT"),
                region=os.environ.get("BACKUP_REGION", "auto"),
                access_key=os.environ["BACKUP_ACCESS_KEY_ID"],
                secret_key=os.environ["BACKUP_SECRET_ACCESS_KEY"],
                key_prefix="media/",  # backup bucket uses media/ prefix for media + db/ for db
            )
            restore_latest_if_missing(_backup_storage, paths.db_path())

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
    # Session cookie hardening (M3 from pentest). Local-only by default
    # but defensible if the user ever puts a reverse proxy in front.
    # SECURE is left False because the dev server is HTTP; a TLS proxy
    # deployment should override via env if it wants the Secure flag.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
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

    from flexlog.web.filters import overall_fmt, star_fill
    app.jinja_env.filters["overall_fmt"] = overall_fmt
    app.jinja_env.filters["star_fill"] = star_fill
    app.jinja_env.filters["humanize_bytes"] = humanize_bytes_filter
    app.jinja_env.filters["iso_local_minute"] = iso_local_minute

    from flexlog.web.filters import vendor_sri
    app.jinja_env.filters["vendor_sri"] = vendor_sri

    from flexlog.web.security_headers import register_security_headers
    register_security_headers(app)

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

    @app.context_processor
    def _inject_status_snapshot() -> dict[str, object]:
        """Compute and inject `status_snapshot` for the status bar on every
        authed render. Skips when:

        - the session is unauthed (auth gate would have redirected the
          request, but Flask still renders error pages via render_template
          which fire context processors).
        - the DB engine isn't attached (master key not unwrapped yet — any
          DB call would crash).

        On any compute error, log a warning and inject nothing so the page
        keeps rendering without the bar."""
        # Local imports keep the module-level import graph clean and
        # let the unauthed-fast-path skip importing services.status.
        from flexlog.db import engine_is_attached, get_db
        from flexlog.services.status import compute_status

        # Mirror _inject_auth_state's direct check rather than calling
        # is_authed(), which has a sliding-window side effect that
        # already fired in the before_request gate.
        authed = bool(
            session.get("authed")
            and session.get("epoch") == current_app.config.get("AUTH_EPOCH")
        )
        if not authed:
            return {}
        if not engine_is_attached():
            return {}
        try:
            snap = compute_status(get_db(), paths.data_dir())
        except Exception:
            current_app.logger.warning(
                "status_snapshot compute failed", exc_info=True,
            )
            return {}
        return {"status_snapshot": snap}

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

    from flexlog.migrations.v1_to_v2 import MigrationError

    @app.errorhandler(MigrationError)
    def _migration_failed(e: MigrationError):
        logging.getLogger(LOGGER_NAME).exception("schema migration failed")
        return _render_template("errors/migration_failed.html", error=str(e)), 500

    # Spawn the DB backup worker thread (only if we wired the backup
    # storage above). The worker waits on after_commit signals and
    # uploads SQLite-backup snapshots to the backup bucket.
    if _backup_storage is not None:
        from flexlog.services.db_backup import register_db_backup_worker
        register_db_backup_worker(app, _backup_storage, paths.db_path())

    return app


def _configure_logging() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
