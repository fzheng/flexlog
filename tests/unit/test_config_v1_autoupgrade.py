"""A pre-v2 config.json (from v0.2.0, missing schema_version) is
auto-upgraded on first load: schema_version=2 is added, sortable=True
is set on each rating dim, and the file is rewritten so subsequent
loads pass validation directly."""
from __future__ import annotations

import json


_V1_CONFIG = {
    "app": {
        "name": "Interview Log",
        "entity_singular": "Guest",
        "entity_plural": "Guests",
        "session_singular": "Interview",
        "session_plural": "Interviews",
    },
    "ratings": [
        {"id": "overall_quality", "label": "Overall Quality",
         "scale_min": 0, "scale_max": 5, "enabled": True},
        {"id": "clarity", "label": "Clarity",
         "scale_min": 0, "scale_max": 5, "enabled": True},
    ],
    "ui_strings": {},
    "limits": {
        "max_custom_rating_dimensions": 6,
        "max_audio_files_per_session": 10,
        "max_video_files_per_session": 10,
        "max_photo_files_per_session": 50,
        "max_upload_mb_per_file": 100,
    },
}


def test_load_or_bootstrap_upgrades_missing_schema_version(tmp_path):
    from flexlog.config_loader import load_or_bootstrap

    path = tmp_path / "config.json"
    path.write_text(json.dumps(_V1_CONFIG))

    cfg = load_or_bootstrap(path)

    # cfg loaded successfully (the validator would have rejected without the upgrade)
    assert cfg.ratings[0].id == "overall_quality"
    assert cfg.ratings[0].sortable is True  # default added during upgrade
    assert cfg.ratings[1].sortable is True

    # File rewritten so subsequent loads don't re-trigger the upgrade
    on_disk = json.loads(path.read_text())
    assert on_disk["schema_version"] == 2
    assert on_disk["ratings"][0]["sortable"] is True
    assert on_disk["ratings"][1]["sortable"] is True


def test_load_or_bootstrap_upgrades_explicit_schema_version_1(tmp_path):
    """A config with `schema_version: 1` is treated the same as missing."""
    from flexlog.config_loader import load_or_bootstrap

    v1 = dict(_V1_CONFIG)
    v1["schema_version"] = 1
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v1))

    cfg = load_or_bootstrap(path)
    assert cfg.ratings[0].sortable is True
    on_disk = json.loads(path.read_text())
    assert on_disk["schema_version"] == 2


def test_load_or_bootstrap_preserves_explicit_sortable_false(tmp_path):
    """If a v1 config already had `sortable: False` on a dim (unusual but
    possible if hand-edited), the upgrade leaves it alone."""
    from flexlog.config_loader import load_or_bootstrap

    v1 = json.loads(json.dumps(_V1_CONFIG))  # deep copy
    v1["ratings"][0]["sortable"] = False
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v1))

    cfg = load_or_bootstrap(path)
    assert cfg.ratings[0].sortable is False
    assert cfg.ratings[1].sortable is True  # default added


def test_load_or_bootstrap_no_op_on_v2_config(tmp_path):
    """An already-v2 config is loaded without rewriting (mtime stays put)."""
    from flexlog.config_loader import load_or_bootstrap, DEFAULT_CONFIG_JSON

    path = tmp_path / "config.json"
    path.write_text(DEFAULT_CONFIG_JSON)
    before = path.stat().st_mtime_ns

    load_or_bootstrap(path)
    after = path.stat().st_mtime_ns

    assert before == after
