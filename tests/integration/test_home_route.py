def test_home_renders_with_default_labels(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # App name from config.app.name
    assert "Interview Log" in body
    # Entity plural from config.app.entity_plural
    assert "Guests" in body
    # ui filter — empty_dashboard default from config.json
    assert "No guests yet. Add your first guest to begin." in body


def test_home_uses_builtin_default_when_user_omits_key(tmp_data_dir):
    """If config.json's ui_strings drops a key, the builtin default fills in."""
    import json
    from flexlog.app import create_app

    cfg_path = tmp_data_dir / "config.json"
    payload = json.loads(cfg_path.read_text())
    payload["ui_strings"] = {}  # wipe all user-supplied keys
    cfg_path.write_text(json.dumps(payload))

    app = create_app()
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Falls back to BUILTIN_UI_DEFAULTS["empty_dashboard"]
    assert "Nothing here yet." in body


def test_home_xss_safe_app_name(tmp_data_dir):
    """An app name containing HTML must be escaped, not rendered as markup."""
    import json
    from flexlog.app import create_app

    cfg_path = tmp_data_dir / "config.json"
    payload = json.loads(cfg_path.read_text())
    payload["app"]["name"] = "<script>alert(1)</script>"
    cfg_path.write_text(json.dumps(payload))

    app = create_app()
    client = app.test_client()
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
