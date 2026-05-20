"""Integration tests for runtime config reload (/settings)."""
from __future__ import annotations

import json


def _read_config(data_dir):
    return json.loads((data_dir / "config.json").read_text())


def _write_config(data_dir, cfg: dict) -> None:
    (data_dir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def test_settings_page_renders(authed_client, tmp_data_dir):
    """The config-path display + reload button live under the Config
    section (v1.0.0 sidebar layout)."""
    resp = authed_client.get("/settings/config")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Reload now" in body
    assert str(tmp_data_dir / "config.json") in body
    assert 'action="/settings/reload"' in body
    assert 'method="post"' in body or 'method="POST"' in body


def test_settings_default_redirects_to_app(authed_client):
    """Bare /settings 303-redirects to /settings/app."""
    resp = authed_client.get("/settings")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/settings/app")


def test_settings_app_section_renders_sidebar_groups(authed_client):
    """The App section page renders the sidebar with both group
    headings and links to every other section."""
    resp = authed_client.get("/settings/app")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Both group headings present
    assert "Application" in body
    assert "System" in body
    # Sidebar tab anchors present
    assert "settings-tab-config" in body
    assert "settings-tab-security" in body


def test_settings_tab_query_param_redirects_to_section(authed_client):
    """Pre-v1.0.0 ?tab=<x> URLs continue to work by 303-redirecting
    to /settings/<x>."""
    resp = authed_client.get("/settings?tab=security")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/settings/security")


def test_settings_invalid_tab_redirects_to_app(authed_client):
    """Unknown ?tab= value 303s to /settings/app (the default)."""
    resp = authed_client.get("/settings?tab=bogus")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/settings/app")


def test_settings_invalid_section_redirects_to_app(authed_client):
    """Unknown /settings/<section> path also 303s to /settings/app."""
    resp = authed_client.get("/settings/bogus")
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/settings/app")


def test_reload_picks_up_new_label(authed_client, tmp_data_dir):
    """Edit config.json mid-run, POST reload, verify new label is rendered."""
    cfg = _read_config(tmp_data_dir)
    cfg.setdefault("ui_strings", {})["new_person"] = "Custom New Friend"
    _write_config(tmp_data_dir, cfg)

    resp = authed_client.post("/settings/reload", follow_redirects=True)
    assert resp.status_code == 200
    assert "Config reloaded" in resp.get_data(as_text=True)

    dash = authed_client.get("/").get_data(as_text=True)
    assert "Custom New Friend" in dash


def test_reload_with_invalid_json_keeps_old_config(authed_client, tmp_data_dir):
    """Corrupt config.json -> flashed error + old labels still active."""
    before = authed_client.get("/people/new").get_data(as_text=True)
    assert "New Person" in before or "New Guest" in before

    (tmp_data_dir / "config.json").write_text("not json {", encoding="utf-8")

    resp = authed_client.post("/settings/reload", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Reload failed" in body

    after = authed_client.get("/people/new").get_data(as_text=True)
    assert ("New Person" in after) or ("New Guest" in after)


def test_reload_post_requires_csrf(csrf_authed_client):
    resp = csrf_authed_client.post("/settings/reload")
    assert resp.status_code == 400


def test_ui_filter_is_not_constant_folded(authed_client, tmp_data_dir):
    """Regression: Jinja2 folds `{{ "key" | ui }}` into a literal at compile
    time unless the filter is marked with @pass_context. Without the marker,
    runtime config reload has no effect on labels — the first compile bakes
    the pre-reload value into the template forever. See app.py's `_ui`
    wrapper for the @pass_context that opts out of this folding.

    This test exercises the same path as test_reload_picks_up_new_label,
    but specifically asserts the failure mode: render dashboard ONCE before
    reloading (forcing the template to compile and triggering folding if
    enabled), THEN reload, THEN re-render and check the label changed.
    """
    # Force the dashboard template to compile.
    pre = authed_client.get("/").get_data(as_text=True)
    assert "New Guest" in pre or "New Person" in pre

    cfg = _read_config(tmp_data_dir)
    cfg.setdefault("ui_strings", {})["new_person"] = "FoldRegressionLabel"
    _write_config(tmp_data_dir, cfg)

    resp = authed_client.post("/settings/reload", follow_redirects=True)
    assert "Config reloaded" in resp.get_data(as_text=True)

    post = authed_client.get("/").get_data(as_text=True)
    assert "FoldRegressionLabel" in post
    assert "New Guest" not in post.split('class="btn btn-primary"')[1].split("</a>")[0]
