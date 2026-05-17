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
    enabled: bool
    sortable: bool
    weight: float


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
    if sv != 3:
        return None, [f"schema_version must be 3; got {sv!r}"]

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
        # Reject removed v2 fields explicitly so users get a clear message
        # rather than silent ignore.
        if "scale_min" in entry or "scale_max" in entry:
            errors.append(
                f"{prefix}: scale_min/scale_max fields removed in schema_version 3; "
                "sub-ratings are locked at 0..5"
            )
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
        weight = entry.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            errors.append(f"{prefix}.weight is required and must be a number in (0, 1]")
            continue
        weight = float(weight)
        if not (0.0 < weight <= 1.0):
            errors.append(f"{prefix}.weight must be in (0, 1]; got {weight}")
            continue
        out.append(
            RatingDimension(
                id=rid, label=label, description=description,
                enabled=enabled, sortable=sortable, weight=weight,
            )
        )
    if enabled_count > _MAX_ENABLED_RATINGS:
        errors.append(
            f"at most {_MAX_ENABLED_RATINGS} enabled rating dimensions allowed; got {enabled_count}"
        )
    # Sum-to-1 check over enabled dims (only if we have all of them parsed).
    if not errors and enabled_count > 0:
        enabled_sum = sum(r.weight for r in out if r.enabled)
        if abs(enabled_sum - 1.0) > 1e-6:
            errors.append(
                f"weights of enabled rating dimensions must sum to 1.0; got {enabled_sum:.4f}"
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
  "schema_version": 3,
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
      "enabled": true,
      "sortable": true,
      "weight": 1.0
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


def _upgrade_pre_v3_config_dict(raw: dict) -> dict:
    """Mutate `raw` from pre-v3 schemas (v0.2.0 with no schema_version, or
    schema_version=1, or schema_version=2) into v3 shape:

    - schema_version becomes 3
    - each rating dim gains `sortable: True` if missing (v1 → v2 carryover)
    - each rating dim has scale_min/scale_max stripped if present
    - enabled dims receive a uniformly-distributed `weight` summing to 1.0
      (rounded to 2 decimals with the last enabled dim absorbing remainder)
    - disabled dims receive a placeholder `weight` of 0.01 if missing

    Note on partial weights: if some but not all enabled dims already carry
    a `weight` field (unusual — pre-v3 configs shouldn't have any), the
    uniform-distribution step still runs across ALL enabled dims and
    overwrites the existing values. The "all-or-nothing" semantics matches
    the common v2→v3 path. To preserve hand-edited partial weights, add
    weights to every enabled dim before launching (the upgrade then becomes
    a no-op on weights).

    Returns the modified dict (also mutates raw for convenience). Caller is
    responsible for writing the result to disk.
    """
    raw["schema_version"] = 3

    ratings = raw.get("ratings")
    if not isinstance(ratings, list):
        return raw

    enabled_indices: list[int] = []
    for i, r in enumerate(ratings):
        if not isinstance(r, dict):
            continue
        # Carry sortable forward (was added in v2)
        if "sortable" not in r:
            r["sortable"] = True
        # Strip removed v2 fields
        r.pop("scale_min", None)
        r.pop("scale_max", None)
        # Disabled dims that lack a weight get a placeholder
        if r.get("enabled", True) is False and "weight" not in r:
            r["weight"] = 0.01
        if r.get("enabled", True):
            enabled_indices.append(i)

    # If the user already wrote weights for enabled dims, leave them alone.
    if enabled_indices and not all(
        "weight" in ratings[i] for i in enabled_indices
    ):
        # At least one enabled dim is missing a weight — distribute uniformly.
        n = len(enabled_indices)
        per = round(1.0 / n, 2)
        for i in enabled_indices[:-1]:
            ratings[i]["weight"] = per
        # Last enabled dim absorbs the rounding remainder so the sum is 1.0.
        ratings[enabled_indices[-1]]["weight"] = round(1.0 - per * (n - 1), 2)

    return raw


def load_or_bootstrap(path: Path) -> Config:
    """Load config.json. If absent, write the default first, then load.

    If the file exists but predates v3 (missing schema_version, or
    schema_version in {1, 2}), auto-upgrade by filling in v3 defaults and
    rewriting the file. Other validation errors are NOT silently rewritten
    — they raise so the user can fix their hand-edited file.
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
        return load_config(path)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return load_config(path)  # surfaces parse error as ConfigError

    if isinstance(raw, dict):
        sv = raw.get("schema_version")
        if sv is None or sv in (1, 2):
            upgraded = _upgrade_pre_v3_config_dict(raw)
            path.write_text(json.dumps(upgraded, indent=2), encoding="utf-8")

    return load_config(path)
