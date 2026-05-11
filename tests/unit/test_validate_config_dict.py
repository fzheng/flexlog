"""validate_config_dict is the pure dict→Config validator extracted from
load_config so the settings UI can re-use it for partial-section saves."""
from __future__ import annotations

import json

from flexlog.config_loader import DEFAULT_CONFIG_JSON, validate_config_dict


def test_validate_config_dict_accepts_default_bootstrap():
    cfg, errors = validate_config_dict(json.loads(DEFAULT_CONFIG_JSON))
    assert errors == []
    assert cfg is not None
    assert cfg.app.name == "Interview Log"


def test_validate_config_dict_returns_errors_for_bad_input():
    cfg, errors = validate_config_dict({"schema_version": 2, "app": "not an object"})
    assert cfg is None
    assert any("app" in e for e in errors)
