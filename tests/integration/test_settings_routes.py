"""GET /settings + POST /settings/app pipeline.

Other tabs are covered by tests in subsequent tasks, but the base
page rendering is asserted here."""
from __future__ import annotations

import json
import re
from pathlib import Path


def _csrf_token(client, path="/settings"):
    body = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    return m.group(1)


def test_settings_page_renders_all_five_tabs(authed_client):
    body = authed_client.get("/settings").get_data(as_text=True)
    for tab in ("app", "ratings", "ui_strings", "limits", "raw"):
        assert f"settings-tab-{tab}" in body  # tab nav link or panel


def test_settings_app_tab_save_persists(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/app",
        data={
            "csrf_token": token,
            "name": "Renamed App",
            "entity_singular": "Subject",
            "entity_plural": "Subjects",
            "session_singular": "Meeting",
            "session_plural": "Meetings",
        },
    )
    assert resp.status_code == 303
    cfg_path = tmp_data_dir / "config.json"
    cfg = json.loads(cfg_path.read_text())
    assert cfg["app"]["name"] == "Renamed App"
    assert cfg["app"]["entity_singular"] == "Subject"


def test_settings_app_tab_rejects_invalid(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    original = (tmp_data_dir / "config.json").read_text()
    resp = csrf_authed_client.post(
        "/settings/app",
        data={
            "csrf_token": token,
            "name": "",  # invalid — required
            "entity_singular": "Subject",
            "entity_plural": "Subjects",
            "session_singular": "Meeting",
            "session_plural": "Meetings",
        },
    )
    assert resp.status_code == 400
    # config.json untouched
    assert (tmp_data_dir / "config.json").read_text() == original
