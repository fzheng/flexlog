from unittest.mock import MagicMock

import pytest

from flexlog.config_loader import AppLabels, Config, Limits
from flexlog.web.filters import (
    BUILTIN_UI_DEFAULTS,
    build_labels_context,
    ui_filter,
)


def _config(ui_strings: dict[str, str] | None = None) -> Config:
    return Config(
        app=AppLabels(
            name="Interview Log",
            entity_singular="Guest",
            entity_plural="Guests",
            session_singular="Interview",
            session_plural="Interviews",
        ),
        ratings=(),
        ui_strings=ui_strings or {},
        limits=Limits(
            max_custom_rating_dimensions=6,
            max_audio_files_per_session=10,
            max_video_files_per_session=10,
            max_photo_files_per_session=50,
            max_upload_mb_per_file=500,
        ),
    )


def test_ui_filter_returns_user_value_when_present():
    cfg = _config({"new_person": "New Guest"})
    assert ui_filter("new_person", cfg) == "New Guest"


def test_ui_filter_falls_back_to_builtin_when_user_omits_key():
    cfg = _config({})
    assert ui_filter("new_person", cfg) == BUILTIN_UI_DEFAULTS["new_person"]


def test_ui_filter_unknown_key_returns_key_itself():
    cfg = _config({})
    # Unknown key — neither user nor builtin defines it. Return the key so
    # the missing-string is visible during development without raising.
    assert ui_filter("totally_unknown_key", cfg) == "totally_unknown_key"


def test_builtin_ui_defaults_includes_minimum_keys():
    # M1 expects at least these keys to render the placeholder dashboard
    for required in ("new_person", "empty_dashboard"):
        assert required in BUILTIN_UI_DEFAULTS


def test_build_labels_context_shape():
    cfg = _config()
    labels = build_labels_context(cfg)
    assert labels["app_name"] == "Interview Log"
    assert labels["entity"]["singular"] == "Guest"
    assert labels["entity"]["plural"] == "Guests"
    assert labels["session"]["singular"] == "Interview"
    assert labels["session"]["plural"] == "Interviews"


def test_builtin_ui_defaults_covers_default_config_keys():
    """Every key shipped in DEFAULT_CONFIG_JSON's ui_strings must also have a
    BUILTIN_UI_DEFAULTS fallback so the missing-key case never shows raw key strings.
    """
    import json

    from flexlog.config_loader import DEFAULT_CONFIG_JSON

    default_keys = set(json.loads(DEFAULT_CONFIG_JSON)["ui_strings"].keys())
    builtin_keys = set(BUILTIN_UI_DEFAULTS.keys())
    missing = default_keys - builtin_keys
    assert not missing, f"BUILTIN_UI_DEFAULTS missing fallbacks for: {missing}"


def test_notes_preview_empty_returns_empty_string():
    from flexlog.web.filters import notes_preview
    assert notes_preview(None) == ""
    assert notes_preview("") == ""
    assert notes_preview("   ") == ""


def test_notes_preview_short_returned_as_is():
    from flexlog.web.filters import notes_preview
    assert notes_preview("hello world") == "hello world"


def test_notes_preview_truncates_with_ellipsis():
    from flexlog.web.filters import notes_preview
    long = "a" * 200
    out = notes_preview(long, length=80)
    assert len(out) <= 81  # 80 chars + ellipsis (the … is one char)
    assert out.endswith("…")


def test_notes_preview_collapses_newlines():
    from flexlog.web.filters import notes_preview
    out = notes_preview("line one\nline two\nline three")
    assert "\n" not in out
    assert out == "line one line two line three"


def test_notes_preview_unicode_preserved():
    from flexlog.web.filters import notes_preview
    assert notes_preview("深入交流") == "深入交流"
