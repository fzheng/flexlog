"""Load and validate the user config.json from $FLEXLOG_DATA_DIR.

Loaded once at app startup; the resulting frozen Config object is stashed on
app.config["FLEXLOG"]. There is no runtime reload — users restart after
editing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_ENABLED_RATINGS = 6


class ConfigError(RuntimeError):
    """Raised when config.json is missing, malformed, or fails validation.

    The message lists every issue found (not just the first).
    """


@dataclass(frozen=True)
class AppLabels:
    name: str
    entity_singular: str
    entity_plural: str
    session_singular: str
    session_plural: str


@dataclass(frozen=True)
class RatingDimension:
    id: str
    label: str
    description: str | None
    scale_min: int
    scale_max: int
    enabled: bool
    sortable: bool = True


@dataclass(frozen=True)
class Limits:
    max_custom_rating_dimensions: int
    max_audio_files_per_session: int
    max_video_files_per_session: int
    max_photo_files_per_session: int
    max_upload_mb_per_file: int


@dataclass(frozen=True)
class Config:
    app: AppLabels
    ratings: tuple[RatingDimension, ...]
    ui_strings: dict[str, str]
    limits: Limits


def validate_config_dict(raw: dict) -> tuple[Config | None, list[str]]:
    """Validate a parsed config dict. Returns (cfg, []) on success or
    (None, [error, ...]) on validation failure. Public for the settings UI
    to reuse for partial-section saves."""
    if not isinstance(raw, dict):
        return None, ["config must be a JSON object at the top level"]

    sv = raw.get("schema_version")
    if sv != 2:
        return None, [f"schema_version must be 2; got {sv!r}"]

    errors: list[str] = []
    app = _parse_app(raw.get("app"), errors)
    ratings = _parse_ratings(raw.get("ratings"), errors)
    ui_strings = _parse_ui_strings(raw.get("ui_strings"), errors)
    limits = _parse_limits(raw.get("limits"), errors)

    if errors:
        return None, errors
    assert app is not None and ratings is not None and limits is not None
    return Config(app=app, ratings=ratings, ui_strings=ui_strings, limits=limits), []


def load_config(path: Path) -> Config:
    """Load and validate config.json. Raises ConfigError with full report."""
    if not path.exists():
        raise ConfigError(f"config.json not found at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"config.json at {path} is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc

    cfg, errors = validate_config_dict(raw)
    if errors:
        joined = "\n  - ".join(errors)
        raise ConfigError(f"config.json at {path} has validation errors:\n  - {joined}")
    assert cfg is not None
    return cfg


def _parse_app(value: Any, errors: list[str]) -> AppLabels | None:
    if not isinstance(value, dict):
        errors.append("`app` section is missing or not an object")
        return None
    fields = ("name", "entity_singular", "entity_plural", "session_singular", "session_plural")
    parsed: dict[str, str] = {}
    ok = True
    for f in fields:
        v = value.get(f)
        if not isinstance(v, str) or v.strip() == "":
            errors.append(f"`app.{f}` must be a non-empty string")
            ok = False
        else:
            parsed[f] = v
    if not ok:
        return None
    return AppLabels(**parsed)


def _parse_ratings(value: Any, errors: list[str]) -> tuple[RatingDimension, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        errors.append("`ratings` must be a list")
        return None
    out: list[RatingDimension] = []
    seen_ids: set[str] = set()
    enabled_count = 0
    for i, entry in enumerate(value):
        prefix = f"ratings[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        rid = entry.get("id")
        if not isinstance(rid, str) or not _SLUG_RE.match(rid):
            errors.append(f"{prefix}.id: rating id must be a slug-shaped string (lowercase, digits, underscore)")
            continue
        if rid in seen_ids:
            errors.append(f"{prefix}.id: duplicate rating id {rid!r}")
            continue
        seen_ids.add(rid)
        label = entry.get("label")
        if not isinstance(label, str) or label.strip() == "":
            errors.append(f"{prefix}.label must be a non-empty string")
            continue
        description = entry.get("description")
        if description is not None and not isinstance(description, str):
            errors.append(f"{prefix}.description must be a string or omitted")
            continue
        scale_min = entry.get("scale_min")
        scale_max = entry.get("scale_max")
        if not isinstance(scale_min, int) or scale_min < 0:
            errors.append(f"{prefix}.scale_min must be an integer >= 0")
            continue
        if not isinstance(scale_max, int) or scale_max > 100 or scale_max <= scale_min:
            errors.append(f"{prefix}.scale_max must be an integer in (scale_min, 100]")
            continue
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{prefix}.enabled must be a boolean")
            continue
        if enabled:
            enabled_count += 1
        sortable = entry.get("sortable", True)
        if not isinstance(sortable, bool):
            errors.append(f"{prefix}.sortable must be a boolean")
            continue
        out.append(
            RatingDimension(
                id=rid,
                label=label,
                description=description,
                scale_min=scale_min,
                scale_max=scale_max,
                enabled=enabled,
                sortable=sortable,
            )
        )
    if enabled_count > _MAX_ENABLED_RATINGS:
        errors.append(
            f"at most {_MAX_ENABLED_RATINGS} enabled rating dimensions allowed; got {enabled_count}"
        )
    return tuple(out)


def _parse_ui_strings(value: Any, errors: list[str]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append("`ui_strings` must be an object of string→string")
        return {}
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            errors.append(f"`ui_strings` entry {k!r} must map a string key to a string value")
            continue
        out[k] = v
    return out


def _parse_limits(value: Any, errors: list[str]) -> Limits | None:
    if not isinstance(value, dict):
        errors.append("`limits` section is missing or not an object")
        return None
    fields = (
        "max_custom_rating_dimensions",
        "max_audio_files_per_session",
        "max_video_files_per_session",
        "max_photo_files_per_session",
        "max_upload_mb_per_file",
    )
    parsed: dict[str, int] = {}
    ok = True
    for f in fields:
        v = value.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            errors.append(f"`limits.{f}` must be a positive integer")
            ok = False
            continue
        parsed[f] = v
    if ok and parsed["max_custom_rating_dimensions"] > _MAX_ENABLED_RATINGS:
        errors.append(
            f"`limits.max_custom_rating_dimensions` must be <= {_MAX_ENABLED_RATINGS}"
        )
        ok = False
    if not ok:
        return None
    return Limits(**parsed)


# Canonical default config.json — used at first-run bootstrap.
# Mirrors the example in PRD §6.1.
DEFAULT_CONFIG_JSON = """{
  "schema_version": 2,
  "app": {
    "name": "Interview Log",
    "entity_singular": "Guest",
    "entity_plural": "Guests",
    "session_singular": "Interview",
    "session_plural": "Interviews"
  },
  "ratings": [
    {
      "id": "energy",
      "label": "Energy",
      "description": "How energetic the session felt",
      "scale_min": 0,
      "scale_max": 5,
      "enabled": true,
      "sortable": true
    }
  ],
  "ui_strings": {
    "new_person": "New Guest",
    "add_session": "Add Interview",
    "search_placeholder": "Search guests or tags",
    "empty_dashboard": "No guests yet. Add your first guest to begin."
  },
  "limits": {
    "max_custom_rating_dimensions": 6,
    "max_audio_files_per_session": 1000000,
    "max_video_files_per_session": 1000000,
    "max_photo_files_per_session": 1000000,
    "max_upload_mb_per_file": 3000
  }
}
"""


def _upgrade_v1_config_dict(raw: dict) -> dict:
    """Mutate `raw` from the v0.2.0 schema shape to v2:

    - add `schema_version: 2`
    - default `sortable: True` on each rating dim that lacks it

    Other fields are untouched so user customizations survive. Caller
    is responsible for writing the result back to disk.
    """
    raw["schema_version"] = 2
    ratings = raw.get("ratings")
    if isinstance(ratings, list):
        for r in ratings:
            if isinstance(r, dict) and "sortable" not in r:
                r["sortable"] = True
    return raw


def load_or_bootstrap(path: Path) -> Config:
    """Load config.json. If absent, write the default first, then load.

    If the file exists but predates the v2 schema (missing `schema_version`
    or `schema_version == 1`), auto-upgrade by filling in the v2 defaults
    and rewriting the file. Other validation errors are NOT silently
    rewritten — they raise so the user can fix their hand-edited file.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
        return load_config(path)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return load_config(path)  # surfaces the parse error as ConfigError

    if isinstance(raw, dict):
        sv = raw.get("schema_version")
        if sv is None or sv == 1:
            upgraded = _upgrade_v1_config_dict(raw)
            path.write_text(json.dumps(upgraded, indent=2), encoding="utf-8")

    return load_config(path)
