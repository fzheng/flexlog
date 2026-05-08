"""Jinja filters and context processors for config-driven UI labels.

The `ui` filter maps short keys to user-supplied strings (from config.json)
with a built-in fallback. The labels context processor exposes app/entity/
session labels under a single `labels` namespace that templates can read.
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from flexlog.config_loader import Config

# Keys used by templates anywhere in the app. M1 needs only what the
# placeholder dashboard renders. Subsequent milestones extend this map.
BUILTIN_UI_DEFAULTS: dict[str, str] = {
    "new_person": "New Person",
    "empty_dashboard": "Nothing here yet.",
    "search_placeholder": "Search",
    "add_session": "Add Session",
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
