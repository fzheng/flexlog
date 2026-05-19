"""Bootstrap flows: first-run set-password + plaintext-data recovery page.

Setup endpoints (`setup.*`) bypass the auth gate (the user can't have
auth state yet) but are state-gated: they refuse if bootstrap_state()
disagrees with the action being requested."""
from __future__ import annotations

import os

from flask import (
    Blueprint, current_app, redirect, render_template, request, url_for,
)

from flexlog import paths
from flexlog.crypto import (
    ARGON2_DEFAULT_PARAMS, aes_gcm_wrap, argon2id_kek, hkdf_subkey,
)
from flexlog.db import Base, attach_engine_at_runtime, make_engine, make_session_factory
from flexlog.kdf_params import KdfParams, write_kdf_params
from flexlog.services.auth import bootstrap_state


setup_bp = Blueprint("setup", __name__, url_prefix="/setup")


_PASSWORD_MIN_LEN = 8


@setup_bp.get("/set-password")
def set_password_form():
    if bootstrap_state(paths.data_dir()) != "needs_setup":
        return redirect(url_for("landing.index"), code=303)
    return render_template("setup/set_password.html", error=None)


@setup_bp.post("/set-password")
def set_password():
    if bootstrap_state(paths.data_dir()) != "needs_setup":
        return redirect(url_for("landing.index"), code=303)

    p1 = request.form.get("password", "")
    p2 = request.form.get("password_confirm", "")

    if not p1:
        return render_template("setup/set_password.html", error="Password is required."), 400
    if len(p1) < _PASSWORD_MIN_LEN:
        return render_template("setup/set_password.html",
                               error=f"Password must be at least {_PASSWORD_MIN_LEN} characters."), 400
    if p1 != p2:
        return render_template("setup/set_password.html",
                               error="Password and confirmation must match."), 400

    # Generate fresh secrets
    kek_salt = os.urandom(16)
    kek_nonce = os.urandom(12)
    master_key = os.urandom(32)
    kek = argon2id_kek(p1, kek_salt, ARGON2_DEFAULT_PARAMS)
    wrapped = aes_gcm_wrap(kek, kek_nonce, master_key)

    # Write the kdf_params.json sidecar (atomic)
    data_dir = paths.data_dir()
    write_kdf_params(
        data_dir / "kdf_params.json",
        KdfParams(
            version=1,
            kek_salt=kek_salt, kek_nonce=kek_nonce, wrapped_master_key=wrapped,
            argon2_time=ARGON2_DEFAULT_PARAMS.time_cost,
            argon2_memory_kib=ARGON2_DEFAULT_PARAMS.memory_kib,
            argon2_parallelism=ARGON2_DEFAULT_PARAMS.parallelism,
        ),
    )

    # Create the encrypted DB
    sqlcipher_key = hkdf_subkey(master_key, b"flexlog/sqlcipher/v1", 32).hex()
    db_path = data_dir / "data" / "encounters.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(db_path, sqlcipher_key)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    # Attach the engine for THIS process (not strictly needed; the user
    # will log in next which will rebuild it, but cleaner this way)
    attach_engine_at_runtime(current_app._get_current_object(), engine, factory)

    return redirect(url_for("landing.index"), code=303)


@setup_bp.get("/recover")
def recover():
    if bootstrap_state(paths.data_dir()) != "needs_recovery":
        return redirect(url_for("landing.index"), code=303)
    return render_template("setup/recover.html",
                           data_dir=str(paths.data_dir()))
