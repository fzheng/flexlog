"""After set-password, the encrypted DB must not contain a vestigial
`auth` table. Earlier versions created one with no reader; M5 removes it."""
from __future__ import annotations


def test_setup_does_not_create_auth_table(csrf_authed_client, csrf_db_session):
    """The conftest `csrf_authed_client` fixture goes through the same
    set_password path that production uses. Verify the dead table is
    gone from the schema."""
    from sqlalchemy import text
    rows = csrf_db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='auth'")
    ).all()
    assert rows == [], (
        "Expected no `auth` table in fresh setup DB, but found one. "
        "M5 should have removed the CREATE TABLE in setup_bp.set_password."
    )


# ---------------------------------------------------------------- landing_bp.submit defensive kdf-is-None branches


def test_landing_post_with_missing_kdf_behaves_like_wrong_password(
    csrf_authed_client, monkeypatch,
):
    """Defensive branch: if bootstrap_state says 'ready' but
    load_kdf_params somehow returns None (file deleted between checks),
    treat the submit as a wrong password — sensitive-shape input goes
    to google.com root, plain input goes to google search."""
    import re
    import sys; monkeypatch.setattr(sys.modules["flexlog.web.landing_bp"], "load_kdf_params",
                       lambda _path: None)

    # Logout first to unauth
    body = csrf_authed_client.get("/dashboard").get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)
    csrf_authed_client.post("/logout", data={"csrf_token": token},
                            follow_redirects=False)

    # Get landing CSRF token
    body = csrf_authed_client.get("/").get_data(as_text=True)
    landing_token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)

    # Password-shaped input + missing kdf → google.com root (no leak)
    resp = csrf_authed_client.post(
        "/", data={"csrf_token": landing_token, "q": "MyPassword1!"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["Location"] == "https://www.google.com/"


def test_landing_post_with_missing_kdf_plain_input_goes_to_search(
    csrf_authed_client, monkeypatch,
):
    """Defensive branch: plain (non-sensitive-shape) input with missing
    kdf → google search redirect."""
    import re
    import sys; monkeypatch.setattr(sys.modules["flexlog.web.landing_bp"], "load_kdf_params",
                       lambda _path: None)

    body = csrf_authed_client.get("/dashboard").get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)
    csrf_authed_client.post("/logout", data={"csrf_token": token},
                            follow_redirects=False)

    body = csrf_authed_client.get("/").get_data(as_text=True)
    landing_token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)

    resp = csrf_authed_client.post(
        "/", data={"csrf_token": landing_token, "q": "weather today"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "google.com/search" in resp.headers["Location"]
