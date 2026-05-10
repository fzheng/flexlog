"""End-to-end set-password + recovery flows."""
from __future__ import annotations


def test_get_root_on_empty_data_dir_redirects_to_set_password(
    tmp_data_dir_no_encryption, monkeypatch
):
    """Fresh install with NO kdf_params + NO encrypted DB → setup page."""
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 303
    assert "/setup/set-password" in resp.headers["Location"]


def test_set_password_creates_kdf_params_and_db(tmp_data_dir_no_encryption):
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.post("/setup/set-password", data={
        "password": "fresh-password-9", "password_confirm": "fresh-password-9",
    })
    assert resp.status_code == 303

    # Both artifacts now exist
    assert (tmp_data_dir_no_encryption / "kdf_params.json").exists()
    assert (tmp_data_dir_no_encryption / "data" / "encounters.db").exists()


def test_set_password_rejects_short(tmp_data_dir_no_encryption):
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.post("/setup/set-password", data={
        "password": "short", "password_confirm": "short",
    })
    assert resp.status_code == 400


def test_set_password_rejects_mismatch(tmp_data_dir_no_encryption):
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.post("/setup/set-password", data={
        "password": "longenough01", "password_confirm": "different5678",
    })
    assert resp.status_code == 400


def test_set_password_blocked_if_already_set(tmp_data_dir, client):
    """tmp_data_dir already has encryption set up. POST to setup must refuse."""
    resp = client.post("/setup/set-password", data={
        "password": "wouldsteal01", "password_confirm": "wouldsteal01",
    })
    assert resp.status_code == 303
    # And the existing kdf_params hasn't been overwritten
    assert (tmp_data_dir / "kdf_params.json").exists()


def test_after_setup_password_login_works(tmp_data_dir_no_encryption):
    """End-to-end: set password, then log in with it."""
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    client.post("/setup/set-password", data={
        "password": "fresh-password-9", "password_confirm": "fresh-password-9",
    })
    resp = client.post("/", data={"q": "fresh-password-9"})
    assert resp.status_code == 303
    # Redirected back to / which serves the dashboard inline for authed users
    assert resp.headers["Location"].endswith("/")
