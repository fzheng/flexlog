"""Integration tests for runtime config reload (/settings)."""
from __future__ import annotations

import json


def _read_config(data_dir):
    return json.loads((data_dir / "config.json").read_text())


def _write_config(data_dir, cfg: dict) -> None:
    (data_dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def test_settings_page_renders(client, tmp_data_dir):
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Reload now" in body
    assert str(tmp_data_dir / "config.json") in body
    assert 'action="/settings/reload"' in body
    assert 'method="post"' in body or 'method="POST"' in body


def test_reload_picks_up_new_label(client, tmp_data_dir):
    """Edit config.json mid-run, POST reload, verify new label is rendered."""
    cfg = _read_config(tmp_data_dir)
    cfg.setdefault("ui_strings", {})["new_person"] = "Custom New Friend"
    _write_config(tmp_data_dir, cfg)

    resp = client.post("/settings/reload", follow_redirects=True)
    assert resp.status_code == 200
    assert "Config reloaded" in resp.get_data(as_text=True)

    dash = client.get("/").get_data(as_text=True)
    assert "Custom New Friend" in dash


def test_reload_with_invalid_json_keeps_old_config(client, tmp_data_dir):
    """Corrupt config.json -> flashed error + old labels still active."""
    before = client.get("/people/new").get_data(as_text=True)
    assert "New Person" in before or "New Guest" in before

    (tmp_data_dir / "config.json").write_text("not json {", encoding="utf-8")

    resp = client.post("/settings/reload", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Reload failed" in body

    after = client.get("/people/new").get_data(as_text=True)
    assert ("New Person" in after) or ("New Guest" in after)


def test_reload_post_requires_csrf(csrf_client):
    resp = csrf_client.post("/settings/reload")
    assert resp.status_code == 400
