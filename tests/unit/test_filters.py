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
    # The dashboard's "New Person" button + empty-state copy are the
    # minimum any flexlog UI render needs to be coherent.
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


# --- humanize_bytes + iso_local_minute filters (status bar wiring) ---


def test_humanize_bytes_filter_registered_and_handles_ints(app):
    with app.app_context():
        f = app.jinja_env.filters["humanize_bytes"]
        assert f(0) == "0 B"
        assert f(1023) == "1023 B"
        assert f(1024) == "1.0 KB"
        assert f(2 * 1024 * 1024 * 1024) == "2.0 GB"


def test_humanize_bytes_filter_returns_empty_on_garbage(app):
    with app.app_context():
        f = app.jinja_env.filters["humanize_bytes"]
        assert f("garbage") == ""
        assert f(None) == ""


def test_iso_local_minute_filter_handles_iso_string(app):
    with app.app_context():
        f = app.jinja_env.filters["iso_local_minute"]
        out = f("2026-05-18T14:23:45.123456+00:00")
        # Output is local-time; we don't know the test machine's TZ, but
        # it's a 16-char string matching the YYYY-MM-DD HH:MM template.
        assert len(out) == 16
        assert out[4] == "-"
        assert out[7] == "-"
        assert out[10] == " "
        assert out[13] == ":"


def test_iso_local_minute_filter_handles_none(app):
    with app.app_context():
        f = app.jinja_env.filters["iso_local_minute"]
        assert f(None) == ""


def test_iso_local_minute_filter_handles_garbage_string(app):
    with app.app_context():
        f = app.jinja_env.filters["iso_local_minute"]
        assert f("not a date") == ""


def test_iso_local_minute_filter_handles_wrong_type(app):
    with app.app_context():
        f = app.jinja_env.filters["iso_local_minute"]
        assert f(12345) == ""


def test_iso_local_minute_filter_handles_naive_datetime(app):
    from datetime import datetime
    with app.app_context():
        f = app.jinja_env.filters["iso_local_minute"]
        # Naive datetime: assumed already local, just strftime'd.
        out = f(datetime(2026, 5, 18, 14, 23, 45))
        assert out == "2026-05-18 14:23"
