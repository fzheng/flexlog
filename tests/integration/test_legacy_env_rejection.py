"""Legacy `.env` files and plaintext DBs trigger the recovery page."""
from __future__ import annotations


def test_legacy_env_file_redirects_to_recover(tmp_data_dir_no_encryption):
    (tmp_data_dir_no_encryption / ".env").write_text("FLEXLOG_ADMIN_PASSWORD_SHA512=abc\n")
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 303
    assert "/setup/recover" in resp.headers["Location"]


def test_plaintext_db_redirects_to_recover(tmp_data_dir_no_encryption):
    (tmp_data_dir_no_encryption / "data").mkdir()
    (tmp_data_dir_no_encryption / "data" / "encounters.db").write_bytes(
        b"SQLite format 3\x00" + b"\x00" * 100
    )
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 303
    assert "/setup/recover" in resp.headers["Location"]


def test_recover_page_renders(tmp_data_dir_no_encryption):
    (tmp_data_dir_no_encryption / ".env").write_text("legacy\n")
    from flexlog.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.get("/setup/recover")
    body = resp.get_data(as_text=True)
    assert "Existing Data Found" in body
    assert str(tmp_data_dir_no_encryption) in body
