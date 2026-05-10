"""Settings page + runtime config reload.

GET  /settings         renders the page (path, last-loaded timestamp, button)
POST /settings/reload  re-runs load_or_bootstrap and swaps app.config["FLEXLOG"]
                       on success; flashes a validator error on failure.

Single-process semantics are sufficient (PRD §13.5: single-user local-only).
The single dict-key write to app.config["FLEXLOG"] is atomic under the GIL,
so concurrent requests can never see a partially-applied config.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)

from flexlog import paths
from flexlog.config_loader import ConfigError, load_or_bootstrap
from flexlog.web.filters import ui_filter

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.get("")
def index():
    return render_template(
        "settings/index.html",
        config_path=str(paths.config_path()),
        loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
    )


@settings_bp.post("/reload")
def reload():
    try:
        new_cfg = load_or_bootstrap(paths.config_path())
    except ConfigError as exc:
        flash(f"{ui_filter('config_reload_failed')}: {exc}", "error")
        return redirect(url_for("settings.index"), code=303)

    current_app.config["FLEXLOG"] = new_cfg
    current_app.config["FLEXLOG_LOADED_AT"] = datetime.now(timezone.utc)
    flash(ui_filter("config_reload_succeeded"), "success")
    return redirect(url_for("settings.index"), code=303)
