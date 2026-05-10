"""Fake Google-clone landing page + search-or-login handler + bootstrap router."""
from __future__ import annotations

from urllib.parse import urlencode

from flask import (
    Blueprint, current_app, redirect, render_template, request, session, url_for,
)

from flexlog import paths
from flexlog.auth import is_authed, mark_authed
from flexlog.crypto import (
    InvalidPassword, aes_gcm_unwrap, argon2id_kek, hkdf_subkey, Argon2Params,
)
from flexlog.db import Base, attach_engine_at_runtime, make_engine, make_session_factory
from flexlog.kdf_params import load_kdf_params
from flexlog.services.auth import bootstrap_state


landing_bp = Blueprint("landing", __name__)


@landing_bp.get("/")
def index():
    state = bootstrap_state(paths.data_dir())
    if state == "needs_setup":
        return redirect(url_for("setup.set_password_form"), code=303)
    if state == "needs_recovery":
        return redirect(url_for("setup.recover"), code=303)

    if is_authed(session, current_app.config):
        from flexlog.web.dashboard_bp import home as dashboard_home
        return dashboard_home()
    brand = current_app.config["FLEXLOG"].app.name
    return render_template("landing/index.html", brand=brand)


@landing_bp.post("/")
def submit():
    state = bootstrap_state(paths.data_dir())
    if state == "needs_setup":
        return redirect(url_for("setup.set_password_form"), code=303)
    if state == "needs_recovery":
        return redirect(url_for("setup.recover"), code=303)

    typed = request.form.get("q", "")
    if not typed:
        brand = current_app.config["FLEXLOG"].app.name
        return render_template("landing/index.html", brand=brand)

    kdf = load_kdf_params(paths.data_dir() / "kdf_params.json")
    if kdf is None:
        # Shouldn't happen if state == "ready"; treat as wrong password
        return redirect(
            "https://www.google.com/search?" + urlencode({"q": typed}), code=303,
        )

    params = Argon2Params(
        time_cost=kdf.argon2_time, memory_kib=kdf.argon2_memory_kib,
        parallelism=kdf.argon2_parallelism,
    )
    kek = argon2id_kek(typed, kdf.kek_salt, params)
    try:
        master_key = aes_gcm_unwrap(kek, kdf.kek_nonce, kdf.wrapped_master_key)
    except InvalidPassword:
        return redirect(
            "https://www.google.com/search?" + urlencode({"q": typed}), code=303,
        )

    # Successful unwrap → log in
    sqlcipher_key = hkdf_subkey(master_key, b"flexlog/sqlcipher/v1", 32).hex()
    db_path = paths.data_dir() / "data" / "encounters.db"
    engine = make_engine(db_path, sqlcipher_key)
    factory = make_session_factory(engine)
    attach_engine_at_runtime(current_app._get_current_object(), engine, factory)

    current_app.config["MASTER_KEY"] = master_key
    mark_authed(session, current_app.config)
    return redirect(url_for("landing.index"), code=303)
