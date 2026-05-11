"""Validation of the v2 config schema fields: schema_version, sortable,
and the relaxed scale_max."""
from __future__ import annotations

from flexlog.config_loader import validate_config_dict


_BASE = {
    "schema_version": 2,
    "app": {
        "name": "App", "entity_singular": "Guest", "entity_plural": "Guests",
        "session_singular": "Interview", "session_plural": "Interviews",
    },
    "ratings": [],
    "ui_strings": {},
    "limits": {
        "max_custom_rating_dimensions": 6,
        "max_audio_files_per_session": 10,
        "max_video_files_per_session": 10,
        "max_photo_files_per_session": 50,
        "max_upload_mb_per_file": 100,
    },
}


def _with_ratings(ratings):
    d = dict(_BASE)
    d["ratings"] = ratings
    return d


def test_schema_version_required_and_must_be_2():
    d = dict(_BASE)
    del d["schema_version"]
    cfg, errors = validate_config_dict(d)
    assert cfg is None and any("schema_version" in e for e in errors)

    d2 = dict(_BASE); d2["schema_version"] = 1
    cfg, errors = validate_config_dict(d2)
    assert cfg is None and any("schema_version" in e for e in errors)


def test_sortable_defaults_to_true_when_omitted():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 5, "enabled": True},
    ]))
    assert errors == []
    assert cfg.ratings[0].sortable is True


def test_sortable_explicit_false_is_preserved():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 5,
         "enabled": True, "sortable": False},
    ]))
    assert errors == []
    assert cfg.ratings[0].sortable is False


def test_scale_max_up_to_100_accepted():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 100, "enabled": True},
    ]))
    assert errors == [] and cfg.ratings[0].scale_max == 100


def test_scale_max_over_100_rejected():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 101, "enabled": True},
    ]))
    assert cfg is None and any("scale_max" in e for e in errors)
