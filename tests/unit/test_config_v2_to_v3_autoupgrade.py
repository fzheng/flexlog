"""A v2 config.json (no weight, scale_min/scale_max present, schema_version=2)
is auto-upgraded to v3 on first load: scale fields stripped, weight
distributed uniformly with the last enabled dim absorbing rounding."""
from __future__ import annotations

import json


def test_load_or_bootstrap_upgrades_v2_two_enabled_dims(tmp_path):
    from flexlog.config_loader import load_or_bootstrap

    v2 = {
        "schema_version": 2,
        "app": {"name": "A", "entity_singular": "G", "entity_plural": "Gs",
                "session_singular": "S", "session_plural": "Ss"},
        "ratings": [
            {"id": "a", "label": "A", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "b", "label": "B", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
        ],
        "ui_strings": {},
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 100,
            "max_video_files_per_session": 100,
            "max_photo_files_per_session": 100,
            "max_upload_mb_per_file": 100,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v2))

    cfg = load_or_bootstrap(path)
    assert cfg.ratings[0].weight == 0.5
    assert cfg.ratings[1].weight == 0.5

    on_disk = json.loads(path.read_text())
    assert on_disk["schema_version"] == 3
    assert "scale_min" not in on_disk["ratings"][0]
    assert "scale_max" not in on_disk["ratings"][0]
    assert abs(on_disk["ratings"][0]["weight"] + on_disk["ratings"][1]["weight"] - 1.0) < 1e-9


def test_load_or_bootstrap_upgrades_v2_three_enabled_dims_rounding(tmp_path):
    """1/3 = 0.333... — rounded to 0.33 per dim; last dim absorbs remainder
    so sum is exactly 1.0."""
    from flexlog.config_loader import load_or_bootstrap

    v2 = {
        "schema_version": 2,
        "app": {"name": "A", "entity_singular": "G", "entity_plural": "Gs",
                "session_singular": "S", "session_plural": "Ss"},
        "ratings": [
            {"id": "a", "label": "A", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "b", "label": "B", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "c", "label": "C", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
        ],
        "ui_strings": {},
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 100,
            "max_video_files_per_session": 100,
            "max_photo_files_per_session": 100,
            "max_upload_mb_per_file": 100,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v2))

    cfg = load_or_bootstrap(path)
    weights = [r.weight for r in cfg.ratings]
    assert weights[0] == 0.33
    assert weights[1] == 0.33
    assert weights[2] == round(1.0 - 0.66, 2)  # 0.34
    assert abs(sum(weights) - 1.0) < 1e-9


def test_load_or_bootstrap_v2_with_disabled_dims(tmp_path):
    """Disabled dims get a placeholder weight; only enabled dims share 1.0."""
    from flexlog.config_loader import load_or_bootstrap

    v2 = {
        "schema_version": 2,
        "app": {"name": "A", "entity_singular": "G", "entity_plural": "Gs",
                "session_singular": "S", "session_plural": "Ss"},
        "ratings": [
            {"id": "a", "label": "A", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "b", "label": "B", "scale_min": 0, "scale_max": 5,
             "enabled": False, "sortable": True},
        ],
        "ui_strings": {},
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 100,
            "max_video_files_per_session": 100,
            "max_photo_files_per_session": 100,
            "max_upload_mb_per_file": 100,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v2))

    cfg = load_or_bootstrap(path)
    assert cfg.ratings[0].weight == 1.0  # only enabled dim absorbs all
    # Disabled dim still has a weight field (placeholder ok)
    assert cfg.ratings[1].weight > 0


def test_load_or_bootstrap_no_op_on_v3(tmp_path):
    """An already-v3 config is not rewritten."""
    from flexlog.config_loader import load_or_bootstrap, DEFAULT_CONFIG_JSON

    path = tmp_path / "config.json"
    path.write_text(DEFAULT_CONFIG_JSON)
    before = path.stat().st_mtime_ns

    load_or_bootstrap(path)
    after = path.stat().st_mtime_ns
    assert before == after
