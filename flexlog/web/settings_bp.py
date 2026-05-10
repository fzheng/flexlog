"""Settings page + runtime config reload.

GET  /settings         renders the page (path, last-loaded timestamp, button)
POST /settings/reload  re-runs load_or_bootstrap and swaps app.config["FLEXLOG"]
                       on success; flashes a validator error on failure.

Single-process semantics are sufficient (PRD §13.5: single-user local-only).
The single dict-key write to app.config["FLEXLOG"] is atomic under the GIL,
so concurrent requests can never see a partially-applied config.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from flexlog import paths
from flexlog.config_loader import ConfigError, load_or_bootstrap
from flexlog.crypto import (
    ARGON2_DEFAULT_PARAMS,
    Argon2Params,
    InvalidPassword,
    aes_gcm_unwrap,
    aes_gcm_wrap,
    argon2id_kek,
)
from flexlog.kdf_params import KdfParams, load_kdf_params, write_kdf_params
from flexlog.web.filters import ui_filter

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

_PASSWORD_MIN_LEN = 8


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


@settings_bp.post("/change-password")
def change_password():
    if not current_app.config.get("MASTER_KEY"):
        abort(403)

    current = request.form.get("current_password", "")
    new1 = request.form.get("new_password", "")
    new2 = request.form.get("new_password_confirm", "")

    if not new1 or len(new1) < _PASSWORD_MIN_LEN:
        flash(f"New password must be at least {_PASSWORD_MIN_LEN} characters.", "error")
        return redirect(url_for("settings.index"), code=303)
    if new1 != new2:
        flash("New password and confirmation must match.", "error")
        return redirect(url_for("settings.index"), code=303)

    kdf_path = paths.data_dir() / "kdf_params.json"
    kdf = load_kdf_params(kdf_path)
    if kdf is None:
        abort(500)

    # Verify current password by trying to unwrap with it
    params = Argon2Params(kdf.argon2_time, kdf.argon2_memory_kib, kdf.argon2_parallelism)
    old_kek = argon2id_kek(current, kdf.kek_salt, params)
    try:
        unwrapped = aes_gcm_unwrap(old_kek, kdf.kek_nonce, kdf.wrapped_master_key)
    except InvalidPassword:
        flash("Current password is incorrect.", "error")
        return redirect(url_for("settings.index"), code=303)

    if unwrapped != current_app.config["MASTER_KEY"]:
        flash("Internal consistency error. Refusing to change password.", "error")
        return redirect(url_for("settings.index"), code=303)

    # Re-wrap the SAME master key with a NEW KEK
    new_kek_salt = os.urandom(16)
    new_kek_nonce = os.urandom(12)
    new_kek = argon2id_kek(new1, new_kek_salt, ARGON2_DEFAULT_PARAMS)
    new_wrapped = aes_gcm_wrap(new_kek, new_kek_nonce, current_app.config["MASTER_KEY"])

    write_kdf_params(
        kdf_path,
        KdfParams(
            version=1,
            kek_salt=new_kek_salt,
            kek_nonce=new_kek_nonce,
            wrapped_master_key=new_wrapped,
            argon2_time=ARGON2_DEFAULT_PARAMS.time_cost,
            argon2_memory_kib=ARGON2_DEFAULT_PARAMS.memory_kib,
            argon2_parallelism=ARGON2_DEFAULT_PARAMS.parallelism,
        ),
    )

    flash("Password changed.", "success")
    return redirect(url_for("settings.index"), code=303)
