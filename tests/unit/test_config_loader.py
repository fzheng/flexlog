import json
from pathlib import Path

import pytest

from flexlog.config_loader import (
    AppLabels,
    Config,
    ConfigError,
    Limits,
    RatingDimension,
    load_config,
)


def _valid_config_dict() -> dict:
    return {
        "app": {
            "name": "Interview Log",
            "entity_singular": "Guest",
            "entity_plural": "Guests",
            "session_singular": "Interview",
            "session_plural": "Interviews",
        },
        "ratings": [
            {
                "id": "overall_quality",
                "label": "Overall Quality",
                "description": "General impression",
                "scale_min": 0,
                "scale_max": 5,
                "enabled": True,
            },
            {
                "id": "clarity",
                "label": "Clarity",
                "scale_min": 0,
                "scale_max": 5,
                "enabled": True,
            },
        ],
        "ui_strings": {
            "new_person": "New Guest",
            "empty_dashboard": "No guests yet.",
        },
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 10,
            "max_video_files_per_session": 10,
            "max_photo_files_per_session": 50,
            "max_upload_mb_per_file": 500,
        },
    }


def _write(tmp_path: Path, payload: dict | str) -> Path:
    p = tmp_path / "config.json"
    if isinstance(payload, str):
        p.write_text(payload)
    else:
        p.write_text(json.dumps(payload))
    return p


def test_load_config_happy_path(tmp_path):
    cfg_path = _write(tmp_path, _valid_config_dict())
    cfg = load_config(cfg_path)
    assert isinstance(cfg, Config)
    assert isinstance(cfg.app, AppLabels)
    assert cfg.app.name == "Interview Log"
    assert cfg.app.entity_singular == "Guest"
    assert isinstance(cfg.limits, Limits)
    assert cfg.limits.max_upload_mb_per_file == 500
    assert isinstance(cfg.ratings, tuple)
    assert all(isinstance(r, RatingDimension) for r in cfg.ratings)
    assert cfg.ratings[0].id == "overall_quality"
    assert cfg.ui_strings["new_person"] == "New Guest"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "does-not-exist.json")


def test_load_config_malformed_json_raises(tmp_path):
    p = _write(tmp_path, "{ this is not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(p)


def test_load_config_top_level_must_be_object(tmp_path):
    p = _write(tmp_path, "[1, 2, 3]")
    with pytest.raises(ConfigError, match="must be a JSON object"):
        load_config(p)


def test_load_config_missing_app_section(tmp_path):
    d = _valid_config_dict()
    del d["app"]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="app"):
        load_config(p)


def test_load_config_app_field_required(tmp_path):
    d = _valid_config_dict()
    del d["app"]["entity_singular"]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="entity_singular"):
        load_config(p)


def test_load_config_app_field_must_be_nonempty_string(tmp_path):
    d = _valid_config_dict()
    d["app"]["entity_singular"] = ""
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="entity_singular"):
        load_config(p)


def test_load_config_too_many_enabled_ratings(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": f"r{i}", "label": f"R{i}", "scale_min": 0, "scale_max": 5, "enabled": True}
        for i in range(7)
    ]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="at most 6"):
        load_config(p)


def test_load_config_disabled_ratings_dont_count(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": f"r{i}", "label": f"R{i}", "scale_min": 0, "scale_max": 5, "enabled": True}
        for i in range(6)
    ] + [
        {"id": "extra", "label": "Extra", "scale_min": 0, "scale_max": 5, "enabled": False}
    ]
    p = _write(tmp_path, d)
    cfg = load_config(p)
    assert len(cfg.ratings) == 7  # all preserved; only enabled count is gated


def test_load_config_duplicate_rating_id(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": "dup", "label": "A", "scale_min": 0, "scale_max": 5, "enabled": True},
        {"id": "dup", "label": "B", "scale_min": 0, "scale_max": 5, "enabled": True},
    ]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="duplicate rating id"):
        load_config(p)


def test_load_config_rating_id_slug_shape(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["id"] = "Has Spaces"
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="rating id"):
        load_config(p)


def test_load_config_rating_scale_out_of_range(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["scale_max"] = 6
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="scale_max"):
        load_config(p)


def test_load_config_rating_scale_min_negative(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["scale_min"] = -1
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="scale_min"):
        load_config(p)


def test_load_config_collects_multiple_errors(tmp_path):
    d = _valid_config_dict()
    d["app"]["name"] = ""
    d["app"]["entity_singular"] = ""
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError) as exc:
        load_config(p)
    msg = str(exc.value)
    assert "name" in msg
    assert "entity_singular" in msg


def test_load_config_limits_must_be_positive_ints(tmp_path):
    d = _valid_config_dict()
    d["limits"]["max_upload_mb_per_file"] = -10
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="max_upload_mb_per_file"):
        load_config(p)


def test_load_config_max_custom_rating_dimensions_capped_at_six(tmp_path):
    d = _valid_config_dict()
    d["limits"]["max_custom_rating_dimensions"] = 7
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="max_custom_rating_dimensions"):
        load_config(p)


def test_load_config_ui_strings_optional(tmp_path):
    d = _valid_config_dict()
    del d["ui_strings"]
    p = _write(tmp_path, d)
    cfg = load_config(p)
    assert cfg.ui_strings == {}
