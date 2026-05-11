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


def test_settings_ui_strings_save(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=ui_strings")
    resp = csrf_authed_client.post(
        "/settings/ui_strings",
        data={
            "csrf_token": token,
            "key": ["new_person", "add_session", "search_placeholder", "empty_dashboard"],
            "value": ["+ Guest", "+ Interview", "Find guests…", "Empty."],
        },
    )
    assert resp.status_code == 303
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert cfg["ui_strings"]["new_person"] == "+ Guest"


def test_settings_limits_save(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=limits")
    resp = csrf_authed_client.post(
        "/settings/limits",
        data={
            "csrf_token": token,
            "max_custom_rating_dimensions": "6",
            "max_audio_files_per_session": "5",
            "max_video_files_per_session": "5",
            "max_photo_files_per_session": "25",
            "max_upload_mb_per_file": "1000",
        },
    )
    assert resp.status_code == 303
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert cfg["limits"]["max_audio_files_per_session"] == 5
    assert cfg["limits"]["max_upload_mb_per_file"] == 1000


def test_settings_ratings_add_dimension(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=ratings")
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            # Repeating-row schema: each row has id, label, scale_min, scale_max,
            # enabled, sortable form fields. Position in the list matches order.
            "rating_id": ["energy", "focus"],
            "rating_label": ["Energy", "Focus"],
            "rating_description": ["How energetic", "How focused"],
            "rating_scale_min": ["0", "0"],
            "rating_scale_max": ["5", "10"],
            "rating_enabled": ["energy", "focus"],
            "rating_sortable": ["energy"],
        },
    )
    assert resp.status_code == 303
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert [r["id"] for r in cfg["ratings"]] == ["energy", "focus"]
    assert cfg["ratings"][1]["scale_max"] == 10
    # 'focus' wasn't in rating_sortable → sortable=False
    assert cfg["ratings"][1]["sortable"] is False


def test_settings_ratings_rename_blocked_if_in_use(csrf_authed_client, tmp_data_dir, db_session, person):
    from flexlog.services.sessions import create_session
    create_session(
        db_session, person_id=person.id, session_date="2026-01-01",
        ratings={"energy": 4}, notes=None, link_urls=[],
    )
    db_session.commit()

    token = _csrf_token(csrf_authed_client, "/settings?tab=ratings")
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            # Attempt to rename 'energy' → 'vigor' while a session still has
            # a rating under 'energy'.
            "rating_original_id": ["energy"],
            "rating_id": ["vigor"],
            "rating_label": ["Vigor"],
            "rating_description": [""],
            "rating_scale_min": ["0"],
            "rating_scale_max": ["5"],
            "rating_enabled": ["vigor"],
            "rating_sortable": ["vigor"],
        },
    )
    assert resp.status_code == 400  # validation rejected
    # config.json untouched
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert cfg["ratings"][0]["id"] == "energy"


def test_settings_raw_json_save(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=raw")
    new_cfg = json.loads((tmp_data_dir / "config.json").read_text())
    new_cfg["app"]["name"] = "From Raw"
    resp = csrf_authed_client.post(
        "/settings/raw",
        data={"csrf_token": token, "raw_json": json.dumps(new_cfg, indent=2)},
    )
    assert resp.status_code == 303
    cfg = json.loads((tmp_data_dir / "config.json").read_text())
    assert cfg["app"]["name"] == "From Raw"


def test_settings_raw_json_rejects_bad_json(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=raw")
    original = (tmp_data_dir / "config.json").read_text()
    resp = csrf_authed_client.post(
        "/settings/raw",
        data={"csrf_token": token, "raw_json": "not json {{"},
    )
    assert resp.status_code == 400
    assert (tmp_data_dir / "config.json").read_text() == original
