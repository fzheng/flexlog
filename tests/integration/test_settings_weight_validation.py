"""Settings Ratings tab: weight column + sum-to-1 validation."""
from __future__ import annotations

import json
import re
from pathlib import Path


def _csrf_token(client, path="/settings?tab=ratings"):
    body = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    return m.group(1)


def test_settings_save_ratings_with_valid_sum(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy", ""],
            "rating_id": ["energy", "depth"],
            "rating_label": ["Energy", "Depth"],
            "rating_description": ["", ""],
            "rating_weight": ["0.4", "0.6"],
            "rating_enabled": ["energy", "depth"],
            "rating_sortable": ["energy", "depth"],
        },
    )
    assert resp.status_code == 303
    cfg = json.loads((tmp_data_dir / "config.json").read_text())
    weights = [r["weight"] for r in cfg["ratings"]]
    assert weights == [0.4, 0.6]


def test_settings_save_ratings_rejects_bad_sum(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    original = (tmp_data_dir / "config.json").read_text()
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy", ""],
            "rating_id": ["energy", "depth"],
            "rating_label": ["Energy", "Depth"],
            "rating_description": ["", ""],
            "rating_weight": ["0.5", "0.4"],  # sum 0.9, not 1.0
            "rating_enabled": ["energy", "depth"],
            "rating_sortable": ["energy"],
        },
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "sum" in body.lower() and "1.0" in body
    # config.json untouched
    assert (tmp_data_dir / "config.json").read_text() == original


def test_settings_save_ratings_rejects_zero_weight(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy"],
            "rating_id": ["energy"],
            "rating_label": ["Energy"],
            "rating_description": [""],
            "rating_weight": ["0"],
            "rating_enabled": ["energy"],
            "rating_sortable": ["energy"],
        },
    )
    assert resp.status_code == 400


def test_settings_save_disabled_dim_weight_excluded_from_sum(csrf_authed_client, tmp_data_dir):
    """Disabled dim's weight isn't counted toward the sum."""
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy", "depth"],
            "rating_id": ["energy", "depth"],
            "rating_label": ["Energy", "Depth"],
            "rating_description": ["", ""],
            "rating_weight": ["1.0", "0.5"],
            "rating_enabled": ["energy"],  # depth NOT enabled
            "rating_sortable": ["energy"],
        },
    )
    # Enabled sum = 1.0 (only energy). Should pass.
    assert resp.status_code == 303
    cfg = json.loads((tmp_data_dir / "config.json").read_text())
    weights = {r["id"]: r["weight"] for r in cfg["ratings"]}
    assert weights == {"energy": 1.0, "depth": 0.5}
