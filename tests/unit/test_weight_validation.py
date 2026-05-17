"""Validation of the v3 weight field: required, positive float in (0, 1],
sum-to-1 across enabled dims with float epsilon tolerance, disabled dims
excluded from the sum."""
from __future__ import annotations

from flexlog.config_loader import validate_config_dict


def _base(ratings):
    return {
        "schema_version": 3,
        "app": {"name": "A", "entity_singular": "G", "entity_plural": "Gs",
                "session_singular": "S", "session_plural": "Ss"},
        "ratings": ratings,
        "ui_strings": {},
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 1000000,
            "max_video_files_per_session": 1000000,
            "max_photo_files_per_session": 1000000,
            "max_upload_mb_per_file": 100,
        },
    }


def _dim(rid, weight, enabled=True):
    return {"id": rid, "label": rid.title(), "description": None,
            "enabled": enabled, "sortable": True, "weight": weight}


def test_single_enabled_dim_with_weight_1_passes():
    cfg, errors = validate_config_dict(_base([_dim("a", 1.0)]))
    assert errors == []
    assert cfg.ratings[0].weight == 1.0


def test_weight_sum_must_equal_1():
    cfg, errors = validate_config_dict(_base([_dim("a", 0.5), _dim("b", 0.4)]))
    assert cfg is None
    assert any("sum to 1.0" in e for e in errors)


def test_weight_sum_with_float_epsilon_accepted():
    # 0.1 + 0.2 + 0.7 = 0.9999999999999999 in IEEE-754; must still pass.
    cfg, errors = validate_config_dict(
        _base([_dim("a", 0.1), _dim("b", 0.2), _dim("c", 0.7)])
    )
    assert errors == []


def test_disabled_dims_excluded_from_sum():
    cfg, errors = validate_config_dict(_base([
        _dim("a", 0.5),
        _dim("b", 0.5),
        _dim("c", 0.7, enabled=False),  # disabled, ignored in sum
    ]))
    assert errors == []
    assert cfg.ratings[2].weight == 0.7  # preserved


def test_weight_must_be_positive():
    cfg, errors = validate_config_dict(_base([_dim("a", 0.0)]))
    assert cfg is None
    assert any("weight" in e and ("(0, 1]" in e or "positive" in e) for e in errors)


def test_weight_must_not_exceed_1():
    cfg, errors = validate_config_dict(_base([_dim("a", 1.5)]))
    assert cfg is None
    assert any("weight" in e for e in errors)


def test_weight_required_field():
    d = {"id": "a", "label": "A", "description": None,
         "enabled": True, "sortable": True}  # no weight
    cfg, errors = validate_config_dict(_base([d]))
    assert cfg is None
    assert any("weight" in e for e in errors)


def test_v3_rejects_scale_fields():
    d = {"id": "a", "label": "A", "description": None,
         "enabled": True, "sortable": True, "weight": 1.0,
         "scale_min": 0, "scale_max": 5}
    cfg, errors = validate_config_dict(_base([d]))
    assert cfg is None
    assert any("scale" in e.lower() for e in errors)


def test_schema_version_must_be_3():
    d = _base([_dim("a", 1.0)])
    d["schema_version"] = 2
    cfg, errors = validate_config_dict(d)
    assert cfg is None
    assert any("schema_version" in e for e in errors)
