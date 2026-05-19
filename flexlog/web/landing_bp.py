"""Fake Google-clone landing page + search-or-login handler + bootstrap router."""
from __future__ import annotations

import re
from urllib.parse import urlencode

from flask import (
    Blueprint, current_app, redirect, render_template, request, session, url_for,
)

from flexlog import paths
from flexlog.auth import is_authed, mark_authed
from flexlog.crypto import (
    InvalidPassword, aes_gcm_unwrap, argon2id_kek, hkdf_subkey, Argon2Params,
)
from flexlog.db import attach_engine_at_runtime, make_engine, make_session_factory
from flexlog.kdf_params import load_kdf_params
from flexlog.services.auth import bootstrap_state


_SSN_HYPHENATED = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_SSN_NINE_DIGITS = re.compile(r"^\d{9}$")


def _looks_like_password(q: str) -> bool:
    """No whitespace, ≥6 chars, contains digit/symbol/case mix.

    There used to be an upper bound of 64 chars. That caused a real
    leak: a 65+ char password-shaped value (e.g. a long passphrase, a
    Bitcoin-seed-style string) failed the heuristic AND failed the
    Argon2 unwrap, so it ended up appended to
    https://www.google.com/search?q=<value> as a 303 redirect — leaking
    the value to browser history and Google's request logs. The
    heuristic only governs leak vs. no-leak (false positives just
    redirect to google.com/ root, which is a UX downgrade not a
    security problem), so erring toward over-blocking is correct.
    """
    if not q or any(c.isspace() for c in q):
        return False
    if len(q) < 6:
        return False
    has_digit = any(c.isdigit() for c in q)
    has_symbol = any(not c.isalnum() and not c.isspace() for c in q)
    has_mixed_case = any(c.islower() for c in q) and any(c.isupper() for c in q)
    return has_digit or has_symbol or has_mixed_case


def _looks_like_ssn(q: str) -> bool:
    """US SSN: XXX-XX-XXXX hyphenated OR XXXXXXXXX (9 plain digits)."""
    if not q:
        return False
    return bool(_SSN_HYPHENATED.match(q) or _SSN_NINE_DIGITS.match(q))


def _luhn_valid(digits: str) -> bool:
    """Mod-10 / Luhn checksum used by every major card brand."""
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _looks_like_cc(q: str) -> bool:
    """13-19 digits (after stripping spaces and hyphens), Luhn-valid."""
    if not q:
        return False
    cleaned = q.replace(" ", "").replace("-", "")
    if not cleaned.isdigit():
        return False
    if not (13 <= len(cleaned) <= 19):
        return False
    return _luhn_valid(cleaned)


def looks_like_sensitive_info(q: str) -> bool:
    """Heuristic: does the typed query look like a password, US SSN, or
    credit-card number? Used to avoid leaking PII through the
    Google-search redirect on a wrong-password submission. Errs toward
    over-blocking — false positives (e.g. 'iphone16') redirect to
    google.com/ instead of google.com/search?q=iphone16, which is a
    minor UX downgrade, not a security problem."""
    return _looks_like_password(q) or _looks_like_ssn(q) or _looks_like_cc(q)


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
        if looks_like_sensitive_info(typed):
            return redirect("https://www.google.com/", code=303)
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
        # Wrong password (or tampered blob). If the typed string looks
        # like PII — password/SSN/CC — redirect to Google's homepage so
        # the value never ends up in a URL bar, Referer, browser history,
        # or Google's logs. Non-PII queries get the normal /search?q=...
        # so the disguise stays intact for casual visitors.
        if looks_like_sensitive_info(typed):
            return redirect("https://www.google.com/", code=303)
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
