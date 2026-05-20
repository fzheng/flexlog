"""Settings page — GET renders the page with any tab; per-section POST
handlers validate + persist atomically.

Five tabs: app, ratings, ui_strings, limits, raw. Each tab is rendered
in its own partial. The GET handler delegates to the partial based on
?tab=<name>. POST handlers validate the merged config dict via
validate_config_dict and write atomically (mode 0600 tmp + rename).
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
from dataclasses import asdict, is_dataclass
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
from sqlalchemy import select

from flexlog import paths
from flexlog.config_loader import (
    ConfigError,
    DEFAULT_CONFIG_JSON,
    load_or_bootstrap,
    validate_config_dict,
)
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
_VALID_TABS = (
    # Application group — config-driven labels, rating dims, limits.
    "app", "ratings", "ui_strings", "limits", "raw",
    # System group — data-dir info + password change. No POST handler
    # at /settings/<tab> for these; they post to /settings/reload and
    # /settings/change-password respectively.
    "config", "security",
)


def _config_as_dict() -> dict:
    """Serialize the live Config dataclass back to a JSON-ready dict."""
    cfg = current_app.config["FLEXLOG"]
    return {
        "schema_version": 3,
        "app": asdict(cfg.app),
        "ratings": [
            {
                "id": r.id, "label": r.label, "description": r.description,
                "enabled": r.enabled, "sortable": r.sortable,
                "weight": r.weight,
            }
            for r in cfg.ratings
        ],
        "ui_strings": dict(cfg.ui_strings),
        "limits": asdict(cfg.limits),
    }


def _atomic_write_config(merged: dict) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f".{path.name}.tmp.{secrets.token_hex(8)}"
    tmp = path.parent / tmp_name
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _in_use_rating_ids() -> set[str]:
    """The set of rating ids that appear in any session.ratings_json. Used to
    block rename/id-change conflicts."""
    from flexlog.db import get_db
    from flexlog.db.models import Session as SessionRow

    db = get_db()
    out: set[str] = set()
    for (raw,) in db.execute(select(SessionRow.ratings_json)).all():
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict):
            out.update(k for k in d.keys() if isinstance(k, str))
    return out


def _persist_and_swap(merged: dict, errors_redir_tab: str):
    """Validate -> write -> swap live config. Returns a Flask response on
    failure (re-render with errors) or None on success."""
    cfg, errors = validate_config_dict(merged)
    if errors:
        return render_template(
            "settings/index.html",
            tab=errors_redir_tab,
            config_dict=merged,
            errors=errors,
            in_use_ids=_in_use_rating_ids(),
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400
    _atomic_write_config(merged)
    current_app.config["FLEXLOG"] = cfg
    current_app.config["FLEXLOG_LOADED_AT"] = datetime.now(timezone.utc)
    flash("Settings saved.", "success")
    return None


@settings_bp.get("")
def index():
    """Bare /settings — redirect to /settings/<section>.

    Default lands on /settings/app. If a ?tab=<x> query is supplied
    (pre-v1.0.0 URL shape), redirect to /settings/<x> if valid,
    otherwise to /settings/app.
    """
    tab = request.args.get("tab")
    if tab and tab in _VALID_TABS:
        return redirect(url_for("settings.section", section=tab), code=303)
    return redirect(url_for("settings.section", section="app"), code=303)


@settings_bp.get("/<section>")
def section(section: str):
    """Per-section settings page. Renders the shared shell template
    with the requested section's partial."""
    if section not in _VALID_TABS:
        return redirect(url_for("settings.section", section="app"), code=303)
    return render_template(
        "settings/index.html",
        tab=section,
        config_dict=_config_as_dict(),
        errors=[],
        in_use_ids=_in_use_rating_ids(),
        config_path=str(paths.config_path()),
        loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
    )


@settings_bp.post("/app")
def save_app():
    merged = _config_as_dict()
    merged["app"] = {
        "name": (request.form.get("name") or "").strip(),
        "entity_singular": (request.form.get("entity_singular") or "").strip(),
        "entity_plural": (request.form.get("entity_plural") or "").strip(),
        "session_singular": (request.form.get("session_singular") or "").strip(),
        "session_plural": (request.form.get("session_plural") or "").strip(),
    }
    result = _persist_and_swap(merged, errors_redir_tab="app")
    if result is not None:
        return result
    return redirect(url_for("settings.section", section="app"), code=303)


@settings_bp.post("/reload")
def reload():
    try:
        new_cfg = load_or_bootstrap(paths.config_path())
    except ConfigError as exc:
        flash(f"{ui_filter('config_reload_failed')}: {exc}", "error")
        return redirect(url_for("settings.section", section="config"), code=303)
    current_app.config["FLEXLOG"] = new_cfg
    current_app.config["FLEXLOG_LOADED_AT"] = datetime.now(timezone.utc)
    flash(ui_filter("config_reload_succeeded"), "success")
    return redirect(url_for("settings.section", section="config"), code=303)


@settings_bp.post("/change-password")
def change_password():
    if not current_app.config.get("MASTER_KEY"):
        abort(403)

    current = request.form.get("current_password", "")
    new1 = request.form.get("new_password", "")
    new2 = request.form.get("new_password_confirm", "")

    if not new1 or len(new1) < _PASSWORD_MIN_LEN:
        flash(f"New password must be at least {_PASSWORD_MIN_LEN} characters.", "error")
        return redirect(url_for("settings.section", section="security"), code=303)
    if new1 != new2:
        flash("New password and confirmation must match.", "error")
        return redirect(url_for("settings.section", section="security"), code=303)

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
        return redirect(url_for("settings.section", section="security"), code=303)

    # Constant-time compare (M2 from pentest). The previous `!=` was a
    # plain bytes compare that short-circuits on the first differing
    # byte. Exploiting that would require a local-write timing oracle,
    # so practically benign — but the rest of the auth path is
    # constant-time and this should be too.
    if not hmac.compare_digest(unwrapped, current_app.config["MASTER_KEY"]):
        flash("Internal consistency error. Refusing to change password.", "error")
        return redirect(url_for("settings.section", section="security"), code=303)

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
    return redirect(url_for("settings.section", section="security"), code=303)


@settings_bp.post("/ui_strings")
def save_ui_strings():
    merged = _config_as_dict()
    keys = request.form.getlist("key")
    values = request.form.getlist("value")
    new_strings: dict[str, str] = {}
    for k, v in zip(keys, values):
        k = (k or "").strip()
        if k:
            new_strings[k] = v
    merged["ui_strings"] = new_strings
    result = _persist_and_swap(merged, errors_redir_tab="ui_strings")
    if result is not None:
        return result
    return redirect(url_for("settings.section", section="ui_strings"), code=303)


@settings_bp.post("/limits")
def save_limits():
    merged = _config_as_dict()
    fields = (
        "max_custom_rating_dimensions",
        "max_audio_files_per_session",
        "max_video_files_per_session",
        "max_photo_files_per_session",
        "max_upload_mb_per_file",
    )
    new_limits = {}
    for f in fields:
        raw = (request.form.get(f) or "").strip()
        try:
            new_limits[f] = int(raw)
        except ValueError:
            new_limits[f] = raw  # let validator reject it
    merged["limits"] = new_limits
    result = _persist_and_swap(merged, errors_redir_tab="limits")
    if result is not None:
        return result
    return redirect(url_for("settings.section", section="limits"), code=303)


def _parse_ratings_form() -> tuple[list[dict], list[tuple[str, str]], list[str]]:
    """Read repeating rating_* form fields. Returns
    (ratings_list, [(orig_id, new_id), ...], errors)."""
    ids = request.form.getlist("rating_id")
    original_ids = request.form.getlist("rating_original_id")
    labels = request.form.getlist("rating_label")
    descriptions = request.form.getlist("rating_description")
    weights = request.form.getlist("rating_weight")
    enabled_set = set(request.form.getlist("rating_enabled"))
    sortable_set = set(request.form.getlist("rating_sortable"))

    n = len(ids)
    if not (len(labels) == len(weights) == n):
        return [], [], ["rating rows are misaligned; refresh the page and try again"]

    ratings: list[dict] = []
    pairs: list[tuple[str, str]] = []
    errors: list[str] = []
    for i in range(n):
        rid = (ids[i] or "").strip()
        if not rid:
            continue
        orig = (original_ids[i] if i < len(original_ids) else "") or ""
        try:
            weight = float(weights[i])
        except (ValueError, TypeError):
            errors.append(f"ratings[{i}]: weight must be a number")
            continue
        if not (0.0 < weight <= 1.0):
            errors.append(f"ratings[{i}]: weight must be in (0, 1]; got {weight}")
            continue
        descr = (descriptions[i] if i < len(descriptions) else "") or None
        ratings.append({
            "id": rid,
            "label": (labels[i] or "").strip(),
            "description": descr if descr else None,
            "enabled": rid in enabled_set,
            "sortable": rid in sortable_set,
            "weight": weight,
        })
        pairs.append((orig, rid))
    return ratings, pairs, errors


@settings_bp.post("/ratings")
def save_ratings():
    new_ratings, id_pairs, parse_errors = _parse_ratings_form()
    if parse_errors:
        return render_template(
            "settings/index.html",
            tab="ratings",
            config_dict=_config_as_dict(),
            errors=parse_errors,
            in_use_ids=_in_use_rating_ids(),
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400

    in_use = _in_use_rating_ids()
    rename_violations = [
        (orig, new) for (orig, new) in id_pairs
        if orig and orig != new and orig in in_use
    ]
    if rename_violations:
        return render_template(
            "settings/index.html",
            tab="ratings",
            config_dict=_config_as_dict(),
            errors=[
                f"cannot rename {orig!r} → {new!r}: existing sessions reference {orig!r}"
                for orig, new in rename_violations
            ],
            in_use_ids=in_use,
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400

    merged = _config_as_dict()
    merged["ratings"] = new_ratings
    result = _persist_and_swap(merged, errors_redir_tab="ratings")
    if result is not None:
        return result
    return redirect(url_for("settings.section", section="ratings"), code=303)


@settings_bp.post("/raw")
def save_raw():
    raw = request.form.get("raw_json", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return render_template(
            "settings/index.html",
            tab="raw",
            config_dict=_config_as_dict(),
            errors=[f"JSON parse error at line {exc.lineno}, column {exc.colno}: {exc.msg}"],
            in_use_ids=_in_use_rating_ids(),
            raw_json=raw,
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400

    result = _persist_and_swap(parsed, errors_redir_tab="raw")
    if result is not None:
        return result
    return redirect(url_for("settings.section", section="raw"), code=303)
