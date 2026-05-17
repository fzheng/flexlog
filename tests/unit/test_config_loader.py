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
        "schema_version": 3,
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
                "enabled": True,
                "weight": 0.5,
            },
            {
                "id": "clarity",
                "label": "Clarity",
                "enabled": True,
                "weight": 0.5,
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
    # 7 enabled dims — over the 6-cap. Weights also won't sum to 1 but the
    # cap error fires first.
    d["ratings"] = [
        {"id": f"r{i}", "label": f"R{i}", "enabled": True, "weight": 1.0 / 7}
        for i in range(7)
    ]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="at most 6"):
        load_config(p)


def test_load_config_disabled_ratings_dont_count(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": f"r{i}", "label": f"R{i}", "enabled": True, "weight": 1.0 / 6}
        for i in range(6)
    ] + [
        {"id": "extra", "label": "Extra", "enabled": False, "weight": 0.01}
    ]
    p = _write(tmp_path, d)
    cfg = load_config(p)
    assert len(cfg.ratings) == 7  # all preserved; only enabled count is gated


def test_load_config_duplicate_rating_id(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = [
        {"id": "dup", "label": "A", "enabled": True, "weight": 0.5},
        {"id": "dup", "label": "B", "enabled": True, "weight": 0.5},
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


def test_load_config_rating_scale_fields_rejected(tmp_path):
    # v3 removed scale_min/scale_max entirely. Presence triggers a clear error.
    d = _valid_config_dict()
    d["ratings"][0]["scale_max"] = 5
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="scale"):
        load_config(p)


def test_load_config_rating_scale_min_rejected(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["scale_min"] = 0
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="scale"):
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


# --- Defensive-branch coverage to satisfy spec §11.4 (≥95% on critical-path modules) ---


def test_load_config_app_section_not_an_object(tmp_path):
    d = _valid_config_dict()
    d["app"] = "not an object"
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="`app` section"):
        load_config(p)


def test_load_config_ratings_not_a_list(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = {"not": "a list"}
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="`ratings` must be a list"):
        load_config(p)


def test_load_config_rating_entry_not_an_object(tmp_path):
    d = _valid_config_dict()
    d["ratings"] = ["not an object"]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match=r"ratings\[0\] must be an object"):
        load_config(p)


def test_load_config_rating_label_empty(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["label"] = ""
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="label"):
        load_config(p)


def test_load_config_rating_description_wrong_type(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["description"] = 123
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="description"):
        load_config(p)


def test_load_config_rating_weight_out_of_range(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["weight"] = 1.5  # > 1.0 → invalid
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="weight"):
        load_config(p)


def test_load_config_rating_enabled_wrong_type(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["enabled"] = "yes"  # not a bool
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="enabled"):
        load_config(p)


def test_load_config_ui_strings_wrong_top_type(tmp_path):
    d = _valid_config_dict()
    d["ui_strings"] = ["not", "a", "dict"]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="ui_strings"):
        load_config(p)


def test_load_config_ui_strings_entry_wrong_type(tmp_path):
    d = _valid_config_dict()
    d["ui_strings"] = {"good_key": "fine", "bad_key": 42}
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="ui_strings"):
        load_config(p)


def test_load_config_limits_section_missing(tmp_path):
    d = _valid_config_dict()
    del d["limits"]
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="`limits` section"):
        load_config(p)


def test_load_config_limits_section_wrong_type(tmp_path):
    d = _valid_config_dict()
    d["limits"] = "nope"
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="`limits` section"):
        load_config(p)


def test_load_config_limits_field_is_bool_rejected(tmp_path):
    """A boolean is technically `int` in Python — make sure the validator rejects it."""
    d = _valid_config_dict()
    d["limits"]["max_upload_mb_per_file"] = True
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="max_upload_mb_per_file"):
        load_config(p)


def test_load_config_rating_id_not_a_string(tmp_path):
    d = _valid_config_dict()
    d["ratings"][0]["id"] = 42
    p = _write(tmp_path, d)
    with pytest.raises(ConfigError, match="rating id"):
        load_config(p)


def test_load_config_ratings_omitted_returns_empty_tuple(tmp_path):
    d = _valid_config_dict()
    del d["ratings"]
    p = _write(tmp_path, d)
    cfg = load_config(p)
    assert cfg.ratings == ()


# --- First-run bootstrap ---

from flexlog.config_loader import DEFAULT_CONFIG_JSON, load_or_bootstrap


def test_load_or_bootstrap_writes_default_when_missing(tmp_path):
    p = tmp_path / "config.json"
    assert not p.exists()
    cfg = load_or_bootstrap(p)
    # File is now present
    assert p.exists()
    # Content matches the canonical default
    assert json.loads(p.read_text()) == json.loads(DEFAULT_CONFIG_JSON)
    # And the loaded Config is consistent
    assert cfg.app.name == "Interview Log"


def test_load_or_bootstrap_existing_valid_file_unchanged(tmp_path):
    p = tmp_path / "config.json"
    payload = _valid_config_dict()
    payload["app"]["name"] = "My Custom Name"
    p.write_text(json.dumps(payload))
    cfg = load_or_bootstrap(p)
    assert cfg.app.name == "My Custom Name"
    # Bootstrap must not overwrite an existing file
    assert json.loads(p.read_text())["app"]["name"] == "My Custom Name"


def test_load_or_bootstrap_existing_malformed_file_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ broken")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_or_bootstrap(p)
    # Must not have overwritten the user's broken file
    assert p.read_text() == "{ broken"


def test_default_config_is_self_consistent(tmp_path):
    """Sanity: the canonical default must validate cleanly."""
    p = tmp_path / "config.json"
    p.write_text(DEFAULT_CONFIG_JSON)
    cfg = load_config(p)
    assert cfg.app.name == "Interview Log"
    # v2 default ships "energy" as the single enabled rating dimension.
    assert any(r.id == "energy" for r in cfg.ratings)
