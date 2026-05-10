"""Jinja filters and context processors for config-driven UI labels.

The `ui` filter maps short keys to user-supplied strings (from config.json)
with a built-in fallback. The labels context processor exposes app/entity/
session labels under a single `labels` namespace that templates can read.
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from flexlog.config_loader import Config

# Built-in fallbacks for every template-rendered string. The user's
# config.json `ui_strings` overrides any of these; missing keys fall back
# to the dictionary below; if neither is set, the `ui_filter` returns the
# raw key so dev can spot the leak. Sections are grouped by feature area,
# in roughly the order they were introduced in the codebase.
BUILTIN_UI_DEFAULTS: dict[str, str] = {
    # Dashboard + search
    "new_person": "New Person",
    "empty_dashboard": "Nothing here yet.",
    "search_placeholder": "Search",
    "add_session": "Add Session",
    # People CRUD
    "edit_person": "Edit",
    "delete_person": "Delete",
    "delete_person_confirm_prompt": "Type the alias to confirm deletion:",
    "save": "Save",
    "cancel": "Cancel",
    "tags_label": "Tags",
    "alias_label": "Alias",
    "tags_help": "Comma-separated. Same tag with different capitalization counts once.",
    "untagged": "Untagged",
    "no_sessions_yet": "No sessions yet.",
    "no_matches_for": "No matches for",
    "delete_alias_did_not_match": "Alias did not match.",
    # Sessions
    "new_session": "New Session",
    "edit_session": "Edit Session",
    "delete_session": "Delete Session",
    "delete_session_confirm": "Delete this session? This cannot be undone.",
    "session_date_label": "Date",
    "overall_score_label": "Overall score",
    "custom_ratings_heading": "Ratings",
    "archived_ratings_heading": "Archived ratings",
    "notes_label": "Notes",
    "links_heading": "Links",
    "link_url_label": "URL",
    "link_label_label": "Label (optional)",
    "add_link": "Add link",
    "remove_link": "Remove",
    "no_links": "No links.",
    "no_notes": "No notes.",
    "session_count": "sessions",
    "session_count_singular": "session",
    "last_session": "Last:",
    "avg_score": "Avg:",
    # Media + Media Library
    "media_library": "Media Library",
    "photos_label": "Photos",
    "audio_label": "Audio",
    "videos_label": "Videos",
    "add_media": "Add media",
    "remove_media": "Remove",
    "filter_all": "All",
    "filter_orphans": "Orphans only",
    "references_one": "ref",
    "references_many": "refs",
    "hard_delete_warning": "This permanently deletes the file from disk and removes all references. Cannot be undone.",
    "delete_button": "Delete",
    # Sort + avatar + accessibility + error pages
    "sort_label": "Sort by",
    "sort_alias": "Alias (A→Z)",
    "sort_last_date": "Last session (newest)",
    "sort_session_count": "Total sessions (most)",
    "sort_avg_score": "Average score (highest)",
    "sort_custom_prefix": "Avg ",
    "avatar_label": "Avatar",
    "avatar_help": "Choose an image; you'll crop it before saving.",
    "clear_avatar_label": "Remove current avatar",
    "crop_save": "Crop & save",
    "crop_reset": "Reset crop",
    "not_found_heading": "Page not found",
    "not_found_body": "The page you tried to open doesn't exist.",
    "too_large_heading": "Upload too large",
    "too_large_body": "That request exceeds the maximum size your data dir is configured to accept.",
    "server_error_heading": "Something went wrong",
    "server_error_body": "An unexpected error occurred. The error has been logged.",
    "skip_to_content": "Skip to content",
    # Settings + runtime config reload
    "settings": "Settings",
    "reload_config": "Reload now",
    "config_path_label": "Config file",
    "config_loaded_at_label": "Loaded at",
    "config_reload_failed": "Reload failed",
    "config_reload_succeeded": "Config reloaded.",
    # Auth + landing page
    "logout": "Logout",
    "search_button": "Search",
    "feeling_lucky": "I'm Feeling Lucky",
    "landing_brand_subtitle": "",
    # Change password (settings page)
    "change_password_heading": "Change password",
    "current_password_label": "Current password",
    "new_password_label": "New password",
    "new_password_confirm_label": "Confirm new password",
    "change_password_submit": "Change password",
    # Setup + recovery
    "set_password_heading": "Set Admin Password",
    "set_password_help": "Choose a strong password — at least 8 characters. You'll use this to log in and to unlock the encrypted database.",
    "password_label": "Password",
    "password_confirm_label": "Confirm password",
    "set_password_submit": "Set Password",
    "recover_heading": "Existing Data Found",
    "recover_body_intro": "This data directory has files but no encrypted database. flexlog v0.2.0+ requires encryption at rest. To proceed:",
    "recover_body_steps": "Steps to recover:",
    "recover_warning": "Do not delete the directory until you have a verified backup.",
}


def ui_filter(key: str, config: Config | None = None) -> str:
    """Look up `key` first in the user's ui_strings, then BUILTIN_UI_DEFAULTS,
    else return `key` itself so missing strings are visible during dev.

    `config` is injectable for unit testing; in production the registered
    Jinja filter pulls it from `current_app.config["FLEXLOG"]`.
    """
    if config is None:
        config = current_app.config["FLEXLOG"]
    if key in config.ui_strings:
        return config.ui_strings[key]
    return BUILTIN_UI_DEFAULTS.get(key, key)


NOTES_PREVIEW_LEN = 80


def notes_preview(notes: str | None, length: int = NOTES_PREVIEW_LEN) -> str:
    """Truncate notes to `length` characters, adding ellipsis if cut.

    Returns an empty string if notes is None or whitespace-only. Newlines
    in the snippet collapse to spaces so the row stays single-line.
    """
    if not notes or not notes.strip():
        return ""
    s = " ".join(notes.split())
    if len(s) <= length:
        return s
    return s[:length].rstrip() + "…"


def build_labels_context(config: Config) -> dict[str, Any]:
    """Build the `labels` dict injected into every template."""
    return {
        "app_name": config.app.name,
        "entity": {
            "singular": config.app.entity_singular,
            "plural": config.app.entity_plural,
        },
        "session": {
            "singular": config.app.session_singular,
            "plural": config.app.session_plural,
        },
    }
