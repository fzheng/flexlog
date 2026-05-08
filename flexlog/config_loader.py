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


def load_config(path: Path) -> Config:
    """Load and validate config.json. Raises ConfigError with full report."""
    if not path.exists():
        raise ConfigError(f"config.json not found at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json at {path} is not valid JSON: {exc.msg} (line {exc.lineno})") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config.json at {path} must be a JSON object at the top level")

    errors: list[str] = []
    app = _parse_app(raw.get("app"), errors)
    ratings = _parse_ratings(raw.get("ratings"), errors)
    ui_strings = _parse_ui_strings(raw.get("ui_strings"), errors)
    limits = _parse_limits(raw.get("limits"), errors)

    if errors:
        joined = "\n  - ".join(errors)
        raise ConfigError(f"config.json at {path} has validation errors:\n  - {joined}")

    # Type checker can't see that errors == [] => all parsers returned non-None.
    assert app is not None and ratings is not None and limits is not None
    return Config(app=app, ratings=ratings, ui_strings=ui_strings, limits=limits)


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
        if not isinstance(scale_max, int) or scale_max > 5 or scale_max <= scale_min:
            errors.append(f"{prefix}.scale_max must be an integer in (scale_min, 5]")
            continue
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"{prefix}.enabled must be a boolean")
            continue
        if enabled:
            enabled_count += 1
        out.append(
            RatingDimension(
                id=rid,
                label=label,
                description=description,
                scale_min=scale_min,
                scale_max=scale_max,
                enabled=enabled,
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
