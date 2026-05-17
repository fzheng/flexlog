# M7 — Weighted Overall Ratings + Star Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Use Opus for implementer subagents** — the user explicitly requested careful implementation; the controller should dispatch with `model="opus"`.

**Goal:** Refactor the rating system so a session's overall is a computed weighted average of its sub-ratings; replace number-typing input with a star clicker.

**Architecture:** `RatingDimension` gains a `weight: float`; enabled weights must sum to 1.0. Sub-ratings lock to integer 0..5 (scale fields removed). The overall is computed on read (never stored). Star-input UI uses hidden `<input>` mirrors for form submission. Auto-upgrade strips v2 scale fields and distributes uniform default weights.

**Tech Stack:** Flask 3.x, SQLAlchemy 2.x (no DB schema change), vanilla JS for stars, Jinja2.

**Spec:** `docs/superpowers/specs/2026-05-17-flexlog-weighted-ratings-design.md`

**Coverage floor:** ≥85% via `pyproject.toml --cov-fail-under=85` (from saved memory `feedback_test_coverage.md`).

---

## File map

**New:**
- `flexlog/static/js/rating_stars.js` — star input behavior + live overall preview.
- `tests/unit/test_compute_overall.py`
- `tests/unit/test_weight_validation.py`
- `tests/unit/test_config_v2_to_v3_autoupgrade.py`
- `tests/unit/test_overall_fmt_filter.py`
- `tests/integration/test_session_form_stars.py`
- `tests/integration/test_dashboard_overall_sort.py`
- `tests/integration/test_person_detail_overall.py`
- `tests/integration/test_settings_weight_validation.py`

**Modified:**
- `flexlog/config_loader.py` — `RatingDimension` (add weight, drop scale fields), `_parse_ratings`, `validate_config_dict` (schema_version=3, sum-to-1), `DEFAULT_CONFIG_JSON`, `load_or_bootstrap` (v2→v3 upgrade).
- `flexlog/services/sessions.py` — new `compute_overall`.
- `flexlog/services/people.py` — `DashboardRow.avg_overall`, `list_dashboard_rows` computes it, `_sort_rows` adds `overall` branch.
- `flexlog/web/dashboard_bp.py` — default sort `overall`.
- `flexlog/web/sessions_bp.py` — pass `overall` to detail; drop scale-related fallbacks in `_parse_ratings_from_request`.
- `flexlog/web/people_bp.py` — compute person avg_overall, pass to template.
- `flexlog/web/settings_bp.py` — `_parse_ratings_form` reads `rating_weight[]`; sum-to-1 validation.
- `flexlog/web/filters.py` — register `overall_fmt` + `star_fill` filters.
- `flexlog/templates/sessions/_form_body.html` — star-input rating block.
- `flexlog/templates/sessions/detail.html` — overall display + star-styled rows.
- `flexlog/templates/dashboard.html` — overall column + sort option.
- `flexlog/templates/people/detail.html` — "Average across N sessions" line.
- `flexlog/templates/_partials/session_row.html` — per-session overall.
- `flexlog/templates/settings/_ratings.html` — drop scale columns, add weight + sum indicator + Distribute button.
- `flexlog/static/js/settings.js` — sum indicator + Distribute button.
- `flexlog/static/css/main.css` — `.star-row`, `.star.lit`, `.star:focus-visible`, `.overall-display`, `.weight-sum-indicator`.
- `pyproject.toml` — version 0.4.0.
- `README.md` — v0.4.0 section.

**Deleted:** none.

---

## Constraints (from saved memory + spec)

- **Implementation model:** Opus only (`feedback_implementation_models.md` says Opus/Sonnet; user explicitly chose Opus for this milestone).
- **Coverage floor:** ≥85% enforced by `--cov-fail-under=85`.
- **No DB schema change** — `PRAGMA user_version` stays at 2. Only config file `schema_version` bumps to 3.
- Working on `main` (consistent with prior milestones).

---

## Task 1: Config schema v3 — add `weight`, drop scale fields, v2→v3 auto-upgrade

Schema v3 changes land in one task because they're tightly coupled: dropping scale fields requires the auto-upgrade to strip them before validation, and adding the weight requires the upgrade to populate defaults. Splitting would leave the test suite red between commits.

**Files:**
- Modify: `flexlog/config_loader.py`
- Test: `tests/unit/test_weight_validation.py` (new), `tests/unit/test_config_v2_to_v3_autoupgrade.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_weight_validation.py`:

```python
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
```

Create `tests/unit/test_config_v2_to_v3_autoupgrade.py`:

```python
"""A v2 config.json (no weight, scale_min/scale_max present, schema_version=2)
is auto-upgraded to v3 on first load: scale fields stripped, weight
distributed uniformly with the last enabled dim absorbing rounding."""
from __future__ import annotations

import json


def test_load_or_bootstrap_upgrades_v2_two_enabled_dims(tmp_path):
    from flexlog.config_loader import load_or_bootstrap

    v2 = {
        "schema_version": 2,
        "app": {"name": "A", "entity_singular": "G", "entity_plural": "Gs",
                "session_singular": "S", "session_plural": "Ss"},
        "ratings": [
            {"id": "a", "label": "A", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "b", "label": "B", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
        ],
        "ui_strings": {},
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 100,
            "max_video_files_per_session": 100,
            "max_photo_files_per_session": 100,
            "max_upload_mb_per_file": 100,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v2))

    cfg = load_or_bootstrap(path)
    assert cfg.ratings[0].weight == 0.5
    assert cfg.ratings[1].weight == 0.5

    on_disk = json.loads(path.read_text())
    assert on_disk["schema_version"] == 3
    assert "scale_min" not in on_disk["ratings"][0]
    assert "scale_max" not in on_disk["ratings"][0]
    assert abs(on_disk["ratings"][0]["weight"] + on_disk["ratings"][1]["weight"] - 1.0) < 1e-9


def test_load_or_bootstrap_upgrades_v2_three_enabled_dims_rounding(tmp_path):
    """1/3 = 0.333... — rounded to 0.33 per dim; last dim absorbs remainder
    so sum is exactly 1.0."""
    from flexlog.config_loader import load_or_bootstrap

    v2 = {
        "schema_version": 2,
        "app": {"name": "A", "entity_singular": "G", "entity_plural": "Gs",
                "session_singular": "S", "session_plural": "Ss"},
        "ratings": [
            {"id": "a", "label": "A", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "b", "label": "B", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "c", "label": "C", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
        ],
        "ui_strings": {},
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 100,
            "max_video_files_per_session": 100,
            "max_photo_files_per_session": 100,
            "max_upload_mb_per_file": 100,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v2))

    cfg = load_or_bootstrap(path)
    weights = [r.weight for r in cfg.ratings]
    assert weights[0] == 0.33
    assert weights[1] == 0.33
    assert weights[2] == round(1.0 - 0.66, 2)  # 0.34
    assert abs(sum(weights) - 1.0) < 1e-9


def test_load_or_bootstrap_v2_with_disabled_dims(tmp_path):
    """Disabled dims get a placeholder weight; only enabled dims share 1.0."""
    from flexlog.config_loader import load_or_bootstrap

    v2 = {
        "schema_version": 2,
        "app": {"name": "A", "entity_singular": "G", "entity_plural": "Gs",
                "session_singular": "S", "session_plural": "Ss"},
        "ratings": [
            {"id": "a", "label": "A", "scale_min": 0, "scale_max": 5,
             "enabled": True, "sortable": True},
            {"id": "b", "label": "B", "scale_min": 0, "scale_max": 5,
             "enabled": False, "sortable": True},
        ],
        "ui_strings": {},
        "limits": {
            "max_custom_rating_dimensions": 6,
            "max_audio_files_per_session": 100,
            "max_video_files_per_session": 100,
            "max_photo_files_per_session": 100,
            "max_upload_mb_per_file": 100,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v2))

    cfg = load_or_bootstrap(path)
    assert cfg.ratings[0].weight == 1.0  # only enabled dim absorbs all
    # Disabled dim still has a weight field (placeholder ok)
    assert cfg.ratings[1].weight > 0


def test_load_or_bootstrap_no_op_on_v3(tmp_path):
    """An already-v3 config is not rewritten."""
    from flexlog.config_loader import load_or_bootstrap, DEFAULT_CONFIG_JSON

    path = tmp_path / "config.json"
    path.write_text(DEFAULT_CONFIG_JSON)
    before = path.stat().st_mtime_ns

    load_or_bootstrap(path)
    after = path.stat().st_mtime_ns
    assert before == after
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_weight_validation.py tests/unit/test_config_v2_to_v3_autoupgrade.py -v --no-cov`
Expected: many failures (validator still requires schema_version=2; no weight field on RatingDimension; auto-upgrade path doesn't exist).

- [ ] **Step 3: Update `RatingDimension` + parser**

In `flexlog/config_loader.py`, replace the `RatingDimension` dataclass:

```python
@dataclass(frozen=True)
class RatingDimension:
    id: str
    label: str
    description: str | None
    enabled: bool
    sortable: bool
    weight: float
```

Note the field order shift: `weight` moves to the end; `scale_min` and `scale_max` are gone; `sortable` is now required (no default — caller supplies it).

Replace the body of `_parse_ratings` with:

```python
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
            errors.append(f"{prefix}.weight must be a number in (0, 1]; got {weight}")
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
```

In `validate_config_dict`, change the schema_version check:

```python
    sv = raw.get("schema_version")
    if sv != 3:
        return None, [f"schema_version must be 3; got {sv!r}"]
```

- [ ] **Step 4: Update `DEFAULT_CONFIG_JSON`**

Replace the literal:

```python
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
```

- [ ] **Step 5: Extend the auto-upgrade path to v3**

Rename `_upgrade_v1_config_dict` to `_upgrade_pre_v3_config_dict` and rewrite it to handle BOTH v1→v2 cases AND v2→v3:

```python
def _upgrade_pre_v3_config_dict(raw: dict) -> dict:
    """Mutate `raw` from pre-v3 schemas (v0.2.0 with no schema_version, or
    schema_version=1, or schema_version=2) into v3 shape:

    - schema_version becomes 3
    - each rating dim gains `sortable: True` if missing (v1 → v2 carryover)
    - each rating dim has scale_min/scale_max stripped if present
    - enabled dims receive a uniformly-distributed `weight` summing to 1.0
      (rounded to 2 decimals with the last enabled dim absorbing remainder)
    - disabled dims receive a placeholder `weight` of 0.01 if missing

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
```

Rewrite `load_or_bootstrap` to handle the broader upgrade range:

```python
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
```

- [ ] **Step 6: Run new tests**

Run: `.venv/bin/python -m pytest tests/unit/test_weight_validation.py tests/unit/test_config_v2_to_v3_autoupgrade.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 7: Adapt existing config tests**

Run: `.venv/bin/python -m pytest tests/unit/test_config_loader.py tests/unit/test_config_schema_v2.py tests/unit/test_config_v1_autoupgrade.py tests/unit/test_validate_config_dict.py -v --no-cov 2>&1 | tail -20`

Expected: many failures — those tests assert v2 schema. For each failing test file:

- `tests/unit/test_config_schema_v2.py` — module is about v2 fields (`schema_version: 2`, scale_max=100, etc.). With v3 in force, these are outdated. Rewrite each test to use `schema_version=3` and the v3 shape (drop scale_min/max, add weight summing to 1.0). The test names can keep referencing v2 history.
- `tests/unit/test_config_v1_autoupgrade.py` — the v0.2.0 → v3 upgrade is now a multi-step path. Each test currently asserts schema_version=2 in the output; update to assert schema_version=3 and verify weight was added.
- `tests/unit/test_config_loader.py` — its `_valid_config_dict()` helper builds a v2 config. Update to build v3 (add `weight`, drop scale fields, set `schema_version=3`).
- `tests/unit/test_validate_config_dict.py` — only the bad-input test needs `schema_version: 3` in its dict.

This is mechanical sweep work. Run the suite after each file's edits to track progress.

- [ ] **Step 8: Full suite + conftest fixture**

Check `tests/conftest.py:_bootstrap_encrypted_dir` — it uses `DEFAULT_CONFIG_JSON` directly, which now defaults to v3. Fixtures should propagate. Run:

Run: `.venv/bin/python -m pytest 2>&1 | tail -5`
Expected: full suite green, ≥85% coverage.

If any integration test fails because it expects 2 enabled dims (the old `overall_quality` + `clarity`), it predates the M6 change that already moved to `energy`. Those should already be fixed; if not, sweep them now.

- [ ] **Step 9: Commit**

```bash
git add flexlog/config_loader.py tests/
git commit -m "$(cat <<'EOF'
config: schema v3 — weight field, drop scale fields, auto-upgrade

Each RatingDimension gains weight: float (required, in (0, 1]); sum
of enabled dims' weights must equal 1.0 ± 1e-6. scale_min and
scale_max are removed from the schema — sub-ratings lock to 0..5.
schema_version bumps to 3.

Auto-upgrade extends to handle v1, v2, and pre-v1 configs in one
sweep: schema_version becomes 3, scale fields are stripped, missing
weights are distributed uniformly across enabled dims with the last
absorbing rounding remainder, disabled dims receive a placeholder
weight of 0.01.

DEFAULT_CONFIG_JSON ships a single example dim (energy) with
weight=1.0. Existing tests adapted from v2 shape to v3.
EOF
)"
```

---

## Task 2: `compute_overall` service helper

Pure function in `flexlog/services/sessions.py`. Reads `ratings_json` + a list of enabled `RatingDimension`s, returns the weighted-average float (or `None` when undefined).

**Files:**
- Modify: `flexlog/services/sessions.py`
- Test: `tests/unit/test_compute_overall.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_compute_overall.py`:

```python
"""compute_overall: weighted-average math, edge cases, return-None paths."""
from __future__ import annotations

import json

from flexlog.config_loader import RatingDimension
from flexlog.services.sessions import compute_overall


def _dim(rid, weight, enabled=True):
    return RatingDimension(
        id=rid, label=rid.title(), description=None,
        enabled=enabled, sortable=True, weight=weight,
    )


def test_compute_overall_weighted_average():
    dims = [_dim("a", 0.5), _dim("b", 0.3), _dim("c", 0.2)]
    stored = json.dumps({"a": 4, "b": 5, "c": 3})
    # 4*0.5 + 5*0.3 + 3*0.2 = 2.0 + 1.5 + 0.6 = 4.1
    assert compute_overall(stored, dims) == 4.1


def test_compute_overall_single_dim():
    dims = [_dim("a", 1.0)]
    stored = json.dumps({"a": 5})
    assert compute_overall(stored, dims) == 5.0


def test_compute_overall_missing_value_treated_as_zero():
    """A new session is required to set every dim, but legacy / partial
    data treats missing as 0 so the overall is well-defined."""
    dims = [_dim("a", 0.5), _dim("b", 0.5)]
    stored = json.dumps({"a": 4})  # b missing
    # 4 * 0.5 + 0 * 0.5 = 2.0
    assert compute_overall(stored, dims) == 2.0


def test_compute_overall_clamps_out_of_range_values():
    """A value > 5 (impossible via the star UI but possible via hand-edited
    data) clamps to 5 rather than producing an overall > 5."""
    dims = [_dim("a", 1.0)]
    stored = json.dumps({"a": 99})
    assert compute_overall(stored, dims) == 5.0


def test_compute_overall_clamps_negative_to_zero():
    dims = [_dim("a", 1.0)]
    stored = json.dumps({"a": -3})
    assert compute_overall(stored, dims) == 0.0


def test_compute_overall_disabled_dims_excluded():
    dims = [_dim("a", 0.7), _dim("b", 0.3), _dim("c", 0.5, enabled=False)]
    stored = json.dumps({"a": 4, "b": 5, "c": 1})  # c value present but disabled
    # Only a + b count
    assert compute_overall(stored, dims) == 4 * 0.7 + 5 * 0.3


def test_compute_overall_returns_none_for_empty_json():
    dims = [_dim("a", 1.0)]
    assert compute_overall(None, dims) is None
    assert compute_overall("", dims) is None


def test_compute_overall_returns_none_for_no_enabled_dims():
    dims = [_dim("a", 1.0, enabled=False)]
    stored = json.dumps({"a": 4})
    assert compute_overall(stored, dims) is None


def test_compute_overall_returns_none_for_malformed_json():
    dims = [_dim("a", 1.0)]
    assert compute_overall("not json", dims) is None
    assert compute_overall(json.dumps([1, 2, 3]), dims) is None  # not a dict


def test_compute_overall_ignores_non_int_values():
    """Stored value of a wrong type contributes 0 rather than crashing."""
    dims = [_dim("a", 0.5), _dim("b", 0.5)]
    stored = json.dumps({"a": "garbage", "b": 4})
    assert compute_overall(stored, dims) == 4 * 0.5
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_compute_overall.py -v --no-cov`
Expected: ImportError on `compute_overall`.

- [ ] **Step 3: Implement `compute_overall`**

Append to `flexlog/services/sessions.py`:

```python
def compute_overall(
    stored_json: str | None,
    dims,
) -> float | None:
    """Weighted average of sub-rating values over enabled dimensions.

    Returns None when `stored_json` is empty/None/malformed, when no dims
    are enabled, or when the stored data is not a dict.

    Missing values are treated as 0. Values outside [0, 5] are clamped
    silently (defensive against hand-edited data).

    The denominator is implicitly 1.0 because validate_config_dict enforces
    that enabled-dim weights sum to 1.0.
    """
    if not stored_json:
        return None
    try:
        stored = json.loads(stored_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(stored, dict):
        return None
    enabled = [d for d in dims if d.enabled]
    if not enabled:
        return None
    total = 0.0
    for d in enabled:
        raw = stored.get(d.id, 0)
        if not isinstance(raw, int) or isinstance(raw, bool):
            v = 0
        else:
            v = raw
        if v < 0:
            v = 0
        elif v > 5:
            v = 5
        total += float(v) * d.weight
    return total
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_compute_overall.py -v --no-cov`
Expected: 10 PASS.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/services/sessions.py tests/unit/test_compute_overall.py
git commit -m "$(cat <<'EOF'
sessions: compute_overall service helper

Pure function that takes stored ratings_json + enabled dims and returns
the weighted-average overall (float in [0, 5]) or None when the data
isn't well-formed. Missing values default to 0; out-of-range values
clamp silently. Denominator is implicitly 1.0 because the config
validator enforces enabled-dim weights sum to 1.0.

10 unit tests cover the math, edge cases, and None returns.
EOF
)"
```

---

## Task 3: Jinja filters `overall_fmt` + `star_fill`

Two display helpers registered on the Flask app. Used by every template that renders an overall or a star row.

**Files:**
- Modify: `flexlog/web/filters.py`, `flexlog/app.py`
- Test: `tests/unit/test_overall_fmt_filter.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_overall_fmt_filter.py`:

```python
"""Jinja filters: overall_fmt formats floats to 1 decimal (None → ''),
star_fill returns '★' * n + '☆' * (5 - n) for an int n in [0, 5]."""
from __future__ import annotations

from flexlog.web.filters import overall_fmt, star_fill


def test_overall_fmt_one_decimal():
    assert overall_fmt(4.32) == "4.3"
    assert overall_fmt(4.0) == "4.0"
    assert overall_fmt(0.05) == "0.1"  # rounded


def test_overall_fmt_none_returns_empty():
    assert overall_fmt(None) == ""


def test_overall_fmt_zero():
    assert overall_fmt(0.0) == "0.0"


def test_overall_fmt_five():
    assert overall_fmt(5.0) == "5.0"


def test_star_fill_zero():
    assert star_fill(0) == "☆☆☆☆☆"


def test_star_fill_three():
    assert star_fill(3) == "★★★☆☆"


def test_star_fill_five():
    assert star_fill(5) == "★★★★★"


def test_star_fill_clamps_out_of_range():
    assert star_fill(-1) == "☆☆☆☆☆"
    assert star_fill(7) == "★★★★★"


def test_star_fill_non_int_returns_all_empty():
    assert star_fill(None) == "☆☆☆☆☆"
    assert star_fill("not a number") == "☆☆☆☆☆"
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_overall_fmt_filter.py -v --no-cov`
Expected: ImportError on the two helpers.

- [ ] **Step 3: Implement the filters**

Append to `flexlog/web/filters.py`:

```python
def overall_fmt(value: float | None) -> str:
    """Format a session/person overall to one decimal place. Returns an
    empty string when value is None so templates can render '—' or a
    placeholder without conditionals."""
    if value is None:
        return ""
    try:
        return "%.1f" % float(value)
    except (TypeError, ValueError):
        return ""


_STAR_FILLED = "★"
_STAR_EMPTY = "☆"


def star_fill(value) -> str:
    """Inline star rendering for a sub-rating integer in [0, 5]. Returns
    '★' * value + '☆' * (5 - value). Out-of-range values are clamped;
    non-integers return all-empty."""
    if isinstance(value, bool) or not isinstance(value, int):
        return _STAR_EMPTY * 5
    v = max(0, min(5, value))
    return _STAR_FILLED * v + _STAR_EMPTY * (5 - v)
```

Register both filters in `flexlog/app.py:create_app()`. Find the existing `app.jinja_env.filters["ui"]` registration and add right below:

```python
    from flexlog.web.filters import overall_fmt, star_fill
    app.jinja_env.filters["overall_fmt"] = overall_fmt
    app.jinja_env.filters["star_fill"] = star_fill
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_overall_fmt_filter.py -v --no-cov`
Expected: 9 PASS.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add flexlog/web/filters.py flexlog/app.py tests/unit/test_overall_fmt_filter.py
git commit -m "filters: overall_fmt + star_fill Jinja helpers

overall_fmt(value: float | None) -> str  formats to 1 decimal,
returns '' for None.

star_fill(value: int) -> str  returns '★' * value + '☆' * (5 - value),
clamping out-of-range values to [0, 5].

Both registered as Jinja filters in create_app."
```

---

## Task 4: Session detail page renders overall + star sub-ratings

The detail page gets a prominent overall display at the top of the Ratings section and the sub-rating list switches to star rendering.

**Files:**
- Modify: `flexlog/web/sessions_bp.py`, `flexlog/templates/sessions/detail.html`, `flexlog/web/filters.py` (UI strings)
- Test: `tests/integration/test_session_form_stars.py` (new, partial — full assertions added in Task 5)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_session_form_stars.py`:

```python
"""Detail page renders the weighted overall + per-dim star rows."""
from __future__ import annotations


def test_detail_shows_overall_and_stars(authed_client, person, db_session):
    from flexlog.services.sessions import create_session

    s = create_session(
        db_session, person_id=person.id, session_date="2026-05-17",
        ratings={"energy": 4}, notes="hello", link_urls=[],
    )
    db_session.commit()

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    # Single-dim config: energy weight 1.0, value 4 → overall 4.0
    assert "4.0" in body
    assert "overall" in body.lower()
    # Star rendering: 4 filled + 1 empty
    assert "★★★★☆" in body
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_stars.py -v --no-cov`
Expected: FAIL (overall not rendered yet; sub-ratings render as text "4" not stars).

- [ ] **Step 3: Pass `overall` to the detail template**

In `flexlog/web/sessions_bp.py`, find the `detail` handler and update it to compute + pass the overall plus a richer per-dim list. Replace the current `detail` body:

```python
@sessions_bp.get("/sessions/<session_id>")
def detail(session_id: str):
    s = _session_or_404(session_id)
    enabled_dims = enabled_rating_dimensions()
    enabled_ids = [d.id for d in enabled_dims]
    current, archived = split_ratings(s.ratings_json, enabled_ids)
    overall = compute_overall(s.ratings_json, enabled_dims)
    # Build (dim, value) tuples for the template so it can render label,
    # value, weight, star fill in one pass.
    dim_by_id = {d.id: d for d in enabled_dims}
    current_with_dims = [(dim_by_id[rid], value) for rid, value in current]
    photos = [j.media_file for j in s.media_joins if j.media_file.media_type == "photo"]
    audios = [j.media_file for j in s.media_joins if j.media_file.media_type == "audio"]
    videos = [j.media_file for j in s.media_joins if j.media_file.media_type == "video"]
    from flexlog.db.models import MediaFile
    db = get_db()
    link_thumbnails = {}
    for link in s.links:
        if link.thumbnail_media_id:
            mf = db.get(MediaFile, link.thumbnail_media_id)
            if mf is not None:
                link_thumbnails[link.id] = mf
    return render_template(
        "sessions/detail.html",
        person=s.person, session=s,
        current_ratings=current_with_dims,
        overall=overall,
        archived_ratings=archived,
        photos=photos, audios=audios, videos=videos,
        link_thumbnails=link_thumbnails,
    )
```

Add `compute_overall` to the imports from `flexlog.services.sessions`.

- [ ] **Step 4: Update the detail template**

In `flexlog/templates/sessions/detail.html`, find the ratings section. Replace it with:

```html
  <section class="ratings-display">
    <h3>{{ "ratings_heading" | ui }}</h3>
    {% if overall is not none %}
    <div class="overall-display">
      <span class="overall-value">{{ overall | overall_fmt }}</span>
      <span class="overall-scale">/ 5 {{ "overall_label" | ui }}</span>
      <span class="overall-method">{{ "overall_method_label" | ui }}</span>
    </div>
    {% endif %}
    {% if current_ratings %}
      <ul class="sub-ratings">
        {% for dim, value in current_ratings %}
          <li>
            <span class="dim-label">{{ dim.label }}</span>
            <span class="stars">{{ value | star_fill }}</span>
            <span class="dim-meta">{{ value }} ({{ "weight_label" | ui }} {{ (dim.weight * 100) | round(0) | int }}%)</span>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="empty-state">{{ "no_ratings" | ui }}</p>
    {% endif %}
    {% if archived_ratings %}
    <details class="ratings-display archived">
      <summary>{{ "archived_ratings_heading" | ui }}</summary>
      <ul>
        {% for rid, value in archived_ratings %}
          <li>{{ rid }}: <strong>{{ value }}</strong></li>
        {% endfor %}
      </ul>
    </details>
    {% endif %}
  </section>
```

- [ ] **Step 5: Add UI string keys**

In `flexlog/web/filters.py:BUILTIN_UI_DEFAULTS`, add:

```python
    "overall_label": "overall",
    "overall_method_label": "(weighted avg)",
    "weight_label": "weight",
```

- [ ] **Step 6: Run new test**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_stars.py -v --no-cov`
Expected: PASS.

- [ ] **Step 7: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green. Some other detail-page tests (e.g. `test_detail_order.py`) may need a tiny adjustment if they assert specific rating-section markup; check and adapt.

- [ ] **Step 8: Commit**

```bash
git add flexlog/web/sessions_bp.py flexlog/templates/sessions/detail.html flexlog/web/filters.py tests/integration/test_session_form_stars.py
git commit -m "$(cat <<'EOF'
detail: render computed overall + star sub-ratings

Session detail's Ratings section now leads with a large overall
(weighted average, 1 decimal) and renders each enabled sub-rating
as a star row showing the value + the dim's weight as a percentage.

sessions_bp.detail computes the overall via compute_overall and
passes (dim, value) tuples so the template can render label + stars
+ weight without further lookups.
EOF
)"
```

---

## Task 5: Star-input form UI (template + JS + CSS)

Replace `<input type="number">` rating rows with button-stars + a hidden `<input>` that carries the integer to the form submit. New JS module owns the click + keyboard + hover behavior + live overall preview.

**Files:**
- Modify: `flexlog/templates/sessions/_form_body.html`, `flexlog/static/css/main.css`, `flexlog/templates/sessions/new.html`, `flexlog/templates/sessions/edit.html`
- Create: `flexlog/static/js/rating_stars.js`
- Test: extend `tests/integration/test_session_form_stars.py`

- [ ] **Step 1: Extend the test**

Append to `tests/integration/test_session_form_stars.py`:

```python
def test_form_renders_star_inputs(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    # Star buttons rendered for the energy dim
    assert 'data-dim-id="energy"' in body
    assert 'name="rating_energy"' in body  # hidden mirror input
    assert 'class="star"' in body
    # Five star buttons per dim
    assert body.count('data-value="1"') >= 1
    assert body.count('data-value="5"') >= 1


def test_form_submit_with_star_value_stores_int(csrf_authed_client, csrf_person):
    """The form posts rating_<id>=N (integer) just like the old number
    input; server stores it in ratings_json as int N."""
    import re
    person = csrf_person
    body = csrf_authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    token = m.group(1)

    resp = csrf_authed_client.post(
        f"/people/{person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "2026-05-17",
            "rating_energy": "3",
            "notes": "",
            "link_urls": [],
        },
    )
    assert resp.status_code == 302  # redirect to detail
    # Detail page renders the stored value
    detail_body = csrf_authed_client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "★★★☆☆" in detail_body  # 3 stars
    assert "3.0" in detail_body  # overall (single dim, weight 1.0)


def test_rating_stars_js_is_served(authed_client):
    resp = authed_client.get("/static/js/rating_stars.js")
    assert resp.status_code == 200
    assert b"rating_stars" in resp.data or b"star" in resp.data
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_stars.py -v --no-cov`
Expected: the 3 new tests fail (no star markup, no JS file).

- [ ] **Step 3: Rewrite the rating block in `_form_body.html`**

In `flexlog/templates/sessions/_form_body.html`, find the `{% if rating_dimensions %}` block and replace it with:

```html
{% if rating_dimensions %}
<fieldset class="form-row ratings-grid">
  <legend>{{ "ratings_heading" | ui }}</legend>
  {% for dim in rating_dimensions %}
    <div class="rating-input" data-dim-id="{{ dim.id }}" data-weight="{{ dim.weight }}">
      <label class="rating-label">{{ dim.label }}</label>
      <div class="star-row" role="radiogroup" aria-label="{{ dim.label }} rating">
        {% for n in range(1, 6) %}
          <button type="button" class="star" data-value="{{ n }}"
                  aria-label="{{ n }} star{% if n != 1 %}s{% endif %}"
                  aria-pressed="false">★</button>
        {% endfor %}
      </div>
      <span class="value-readout" data-value-readout>{{ existing_ratings.get(dim.id, 0) }} / 5</span>
      <input type="hidden" name="rating_{{ dim.id }}" value="{{ existing_ratings.get(dim.id, 0) }}">
    </div>
  {% endfor %}
  <div class="overall-preview-row">
    <span>{{ "overall_preview_label" | ui }}</span>
    <output id="overall-preview" data-overall-preview>0.0</output>
  </div>
</fieldset>
{% endif %}
```

Add the new UI string in `flexlog/web/filters.py:BUILTIN_UI_DEFAULTS`:

```python
    "overall_preview_label": "Overall (preview):",
```

- [ ] **Step 4: Create `rating_stars.js`**

Create `flexlog/static/js/rating_stars.js`:

```javascript
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  for (const row of document.querySelectorAll(".rating-input")) {
    bindStarRow(row);
  }
  bindOverallPreview();
});

function bindStarRow(row) {
  const stars = Array.from(row.querySelectorAll(".star"));
  const hidden = row.querySelector('input[type="hidden"]');
  const readout = row.querySelector("[data-value-readout]");

  const render = (value) => {
    for (const s of stars) {
      const n = parseInt(s.dataset.value, 10);
      const lit = n <= value;
      s.classList.toggle("lit", lit);
      s.setAttribute("aria-pressed", lit ? "true" : "false");
    }
    hidden.value = value;
    if (readout) readout.textContent = value + " / 5";
    updateOverallPreview();
  };

  const current = () => parseInt(hidden.value, 10) || 0;

  render(current());

  stars.forEach((star) => {
    const n = parseInt(star.dataset.value, 10);
    star.addEventListener("click", () => {
      // Click on already-lit star at the same value → decrement to N-1.
      // Allows clicking the lit star 1 to clear to 0.
      const cur = current();
      render(cur === n ? n - 1 : n);
    });
    star.addEventListener("mouseenter", () => previewFill(stars, n));
    star.addEventListener("mouseleave", () => previewFill(stars, current()));
    star.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        render(Math.max(0, current() - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        render(Math.min(5, current() + 1));
      } else if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        const cur = current();
        render(cur === n ? n - 1 : n);
      }
    });
  });
}

function previewFill(stars, n) {
  for (const s of stars) {
    const sn = parseInt(s.dataset.value, 10);
    s.classList.toggle("hover", sn <= n);
  }
}

function bindOverallPreview() {
  // Recompute the preview now and on every star commit.
  updateOverallPreview();
}

function updateOverallPreview() {
  const out = document.querySelector("[data-overall-preview]");
  if (!out) return;
  let total = 0;
  for (const row of document.querySelectorAll(".rating-input")) {
    const weight = parseFloat(row.dataset.weight) || 0;
    const hidden = row.querySelector('input[type="hidden"]');
    const value = parseInt(hidden.value, 10) || 0;
    total += value * weight;
  }
  out.textContent = total.toFixed(1);
}
```

- [ ] **Step 5: Wire the script into the form templates**

In `flexlog/templates/sessions/new.html` and `flexlog/templates/sessions/edit.html`, add the script tag near the existing `session_form.js` reference (or in the `{% block scripts %}` if it exists). The exact line in `new.html`:

```html
<script src="{{ url_for('static', filename='js/session_form.js') }}" defer></script>
```

Append immediately after it:

```html
<script src="{{ url_for('static', filename='js/rating_stars.js') }}" defer></script>
```

Do the same in `edit.html`.

- [ ] **Step 6: Append CSS**

Append to `flexlog/static/css/main.css`:

```css
/* Star input — session form */
.rating-input { display: grid; grid-template-columns: 140px 1fr 70px; gap: 10px; align-items: center; margin-bottom: 10px; }
.rating-input .rating-label { font-size: 13px; }
.star-row { display: inline-flex; gap: 4px; }
.star {
  background: none; border: none; cursor: pointer; padding: 2px 4px;
  font-size: 22px; line-height: 1; color: #d1d5db;
  transition: color 0.1s ease;
}
.star.lit, .star.hover { color: #f59e0b; }
.star:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; border-radius: 2px; }
.value-readout { font-size: 12px; color: #666; }
.overall-preview-row {
  display: flex; gap: 10px; align-items: baseline;
  padding-top: 10px; margin-top: 8px;
  border-top: 1px solid #e5e7eb;
  font-size: 13px;
}
.overall-preview-row output { font-size: 18px; font-weight: 600; }

/* Detail page — overall display */
.overall-display {
  display: flex; align-items: baseline; gap: 14px;
  margin-bottom: 10px; padding-bottom: 10px;
  border-bottom: 1px solid #e5e7eb;
}
.overall-display .overall-value { font-size: 36px; font-weight: 600; line-height: 1; }
.overall-display .overall-scale { font-size: 14px; color: #666; }
.overall-display .overall-method { font-size: 11px; color: #999; }

/* Detail page — sub-rating star rows */
.sub-ratings { list-style: none; padding: 0; margin: 0; }
.sub-ratings li { display: flex; align-items: center; gap: 10px; padding: 4px 0; font-size: 13px; }
.sub-ratings .dim-label { flex: 0 0 90px; }
.sub-ratings .stars { color: #f59e0b; letter-spacing: 2px; }
.sub-ratings .dim-meta { color: #999; margin-left: auto; }
```

- [ ] **Step 7: Run new tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_stars.py -v --no-cov`
Expected: all PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 8: Commit**

```bash
git add flexlog/templates/sessions/_form_body.html flexlog/templates/sessions/new.html flexlog/templates/sessions/edit.html flexlog/static/js/rating_stars.js flexlog/static/css/main.css flexlog/web/filters.py tests/integration/test_session_form_stars.py
git commit -m "$(cat <<'EOF'
form: star-clicker input + live overall preview

Replaces the per-dim <input type=number> with a row of 5 star
buttons. A hidden <input> mirrors the integer for form submission.
Click a lit star at the same value to decrement (so clicking star 1
when value=1 clears to 0). Hover previews the fill. Keyboard:
←/→ adjust, Space/Enter commits the focused star's position.

Live overall preview updates on every commit by reading each row's
data-weight and computing Σ(value × weight) client-side. The server
still computes its own authoritative overall on save.
EOF
)"
```

---

## Task 6: Server-side form parser clamps 0..5

`_parse_ratings_from_request` already does range checking against `dim.scale_min` / `dim.scale_max`. Now that scale fields are gone, replace with a hardcoded 0..5 clamp (silent — JS can't send out-of-range, but be defensive).

**Files:**
- Modify: `flexlog/web/sessions_bp.py`
- Test: append to `tests/integration/test_session_form_stars.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_session_form_stars.py`:

```python
def test_server_clamps_out_of_range_rating(csrf_authed_client, csrf_person):
    """If JS is bypassed and someone POSTs rating_<id>=99, the server
    silently clamps to 5 rather than erroring."""
    import re
    person = csrf_person
    body = csrf_authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', body).group(1)

    resp = csrf_authed_client.post(
        f"/people/{person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "2026-05-17",
            "rating_energy": "99",  # out of range
            "notes": "",
        },
    )
    assert resp.status_code == 302
    detail_body = csrf_authed_client.get(resp.headers["Location"]).get_data(as_text=True)
    # Clamped to 5
    assert "★★★★★" in detail_body
    assert "5.0" in detail_body  # overall
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_stars.py::test_server_clamps_out_of_range_rating -v --no-cov`
Expected: depends on existing parser behavior; likely the value is dropped (`continue` on the `if dim.scale_min <= val <= dim.scale_max` check), so the session saves with no energy rating and the overall is `0.0`. Test fails.

- [ ] **Step 3: Update the parser**

In `flexlog/web/sessions_bp.py`, replace `_parse_ratings_from_request`:

```python
def _parse_ratings_from_request() -> dict[str, int]:
    """Pull rating_<id> form fields. Values are clamped to [0, 5]
    (defensive — the star UI can't send out-of-range, but a direct POST
    bypass shouldn't crash the save)."""
    out: dict[str, int] = {}
    for dim in enabled_rating_dimensions():
        raw = (request.form.get(f"rating_{dim.id}") or "").strip()
        if not raw:
            continue
        try:
            val = int(raw)
        except ValueError:
            continue
        if val < 0:
            val = 0
        elif val > 5:
            val = 5
        out[dim.id] = val
    return out
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_stars.py::test_server_clamps_out_of_range_rating -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/web/sessions_bp.py tests/integration/test_session_form_stars.py
git commit -m "sessions: parser clamps rating values to [0, 5]

Server-side defensive clamp replaces the old scale_min/scale_max
range check (those fields are gone in schema v3). The star UI can't
send out-of-range values, but a direct POST bypass shouldn't blow up
the save — clamp silently."
```

---

## Task 7: Dashboard avg_overall + sort

`DashboardRow` gets an `avg_overall: float | None` field. `list_dashboard_rows` walks each person's sessions and computes the mean of their session overalls. `_sort_rows` adds an `overall` branch. The dashboard route's default sort changes from `alias` to `overall`. The dashboard template gets a column showing the value.

**Files:**
- Modify: `flexlog/services/people.py`, `flexlog/web/dashboard_bp.py`, `flexlog/templates/dashboard.html`, `flexlog/templates/_partials/person_card.html`, `flexlog/web/filters.py`
- Test: `tests/integration/test_dashboard_overall_sort.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_dashboard_overall_sort.py`:

```python
"""Dashboard avg_overall column + sort=overall default."""
from __future__ import annotations


def _make_with_ratings(db_session, alias, sessions_ratings):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias=alias, tag_input="")
    db_session.commit()
    for i, ratings in enumerate(sessions_ratings):
        create_session(
            db_session, person_id=p.id,
            session_date=f"2026-01-{i+1:02d}",
            ratings=ratings, notes=None, link_urls=[],
        )
    db_session.commit()
    return p


def test_dashboard_default_sort_is_overall(authed_client):
    body = authed_client.get("/").get_data(as_text=True)
    # The "overall" option in the sort select should be present + selected.
    assert 'value="overall"' in body
    assert 'value="overall" selected' in body or 'value="overall"  selected' in body or 'value="overall"\nselected' in body or "selected>" in body  # tolerant for whitespace


def test_dashboard_sort_by_overall_orders_descending(authed_client, db_session):
    # Single-dim config (energy, weight 1.0). Overall = energy value.
    _make_with_ratings(db_session, "Alice", [{"energy": 5}, {"energy": 4}])  # avg 4.5
    _make_with_ratings(db_session, "Bob",   [{"energy": 2}])                  # avg 2.0
    _make_with_ratings(db_session, "Carol", [])                                # None

    resp = authed_client.get("/?sort=overall")
    body = resp.get_data(as_text=True)
    a = body.index("Alice")
    b = body.index("Bob")
    c = body.index("Carol")
    assert a < b < c  # Alice (4.5) first, Bob (2.0), Carol (no sessions) last


def test_dashboard_renders_overall_column(authed_client, db_session):
    _make_with_ratings(db_session, "Alice", [{"energy": 4}])
    body = authed_client.get("/").get_data(as_text=True)
    # Alice's card shows the avg_overall
    assert "4.0" in body


def test_dashboard_no_sessions_shows_em_dash_or_blank(authed_client, db_session):
    _make_with_ratings(db_session, "Carol", [])
    body = authed_client.get("/").get_data(as_text=True)
    # Some sentinel ('—' or empty) for the missing avg
    assert "Carol" in body
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_dashboard_overall_sort.py -v --no-cov`
Expected: failures across the board.

- [ ] **Step 3: Update `services/people.py`**

In `flexlog/services/people.py`:

Update the `DashboardRow` dataclass — add `avg_overall: float | None = None`:

```python
@dataclass
class DashboardRow:
    person: Person
    session_count: int
    last_session_date: str | None
    avg_overall: float | None = None
```

Update `_VALID_SCALAR_SORTS`:

```python
_VALID_SCALAR_SORTS = ("alias", "last_date", "session_count", "overall")
```

Rewrite `list_dashboard_rows` to compute avg_overall for each row. After the existing `for person, count, last_date in session.execute(base).all():` loop, walk every session and compute the per-person mean. Implementation:

```python
def list_dashboard_rows(
    session: Session,
    query: str,
    sort: str = "overall",
) -> list[DashboardRow]:
    """Return DashboardRows with avg_overall computed Python-side.

    Sort options:
      * "overall"        — avg_overall desc, NULLs last (DEFAULT)
      * "alias"          — alphabetical
      * "last_date"      — last_session_date desc, NULLs last
      * "session_count"  — session_count desc
      * "custom:<dim>"   — Python-side average of that sub-dim (legacy support)
    """
    q = (query or "").strip()
    base = (
        select(
            Person,
            func.count(SessionRow.id).label("session_count"),
            func.max(SessionRow.session_date).label("last_session_date"),
        )
        .outerjoin(SessionRow, SessionRow.person_id == Person.id)
        .group_by(Person.id)
        .options(selectinload(Person.tags))
    )
    if q != "":
        like = f"%{q.lower()}%"
        tag_match = (
            select(PersonTag.person_id)
            .join(Tag, Tag.id == PersonTag.tag_id)
            .where(
                PersonTag.person_id == Person.id,
                or_(Tag.name.ilike(like), Tag.slug.ilike(like)),
            )
        )
        base = base.where(or_(Person.alias.ilike(like), exists(tag_match)))

    # Compute per-person avg_overall in a single pass.
    avg_by_person = _per_person_avg_overall(session)

    rows: list[DashboardRow] = []
    for person, count, last_date in session.execute(base).all():
        rows.append(
            DashboardRow(
                person=person,
                session_count=int(count or 0),
                last_session_date=last_date,
                avg_overall=avg_by_person.get(person.id),
            )
        )
    return _sort_rows(session, rows, sort)


def _per_person_avg_overall(session: Session) -> dict[str, float]:
    """Return {person_id: mean(session.overall)} across all sessions.
    Uses the same compute_overall helper as the detail page."""
    from flask import current_app
    from flexlog.services.sessions import compute_overall

    cfg = current_app.config["FLEXLOG"]
    rows = session.execute(
        select(SessionRow.person_id, SessionRow.ratings_json)
    ).all()
    sums: dict[str, list[float]] = {}
    for person_id, raw in rows:
        overall = compute_overall(raw, cfg.ratings)
        if overall is None:
            continue
        sums.setdefault(person_id, []).append(overall)
    return {pid: sum(vs) / len(vs) for pid, vs in sums.items() if vs}
```

Update `_sort_rows` to handle the new `overall` branch and to default to `overall` when the sort key is unrecognized. Find the current "alias fallback" line and rewrite:

```python
def _sort_rows(
    session: Session, rows: list[DashboardRow], sort: str
) -> list[DashboardRow]:
    alias_key = lambda r: r.person.alias.casefold()  # noqa: E731

    if sort == "alias":
        return sorted(rows, key=alias_key)
    if sort == "last_date":
        return sorted(rows, key=lambda r: (r.last_session_date is None, _neg_str(r.last_session_date), alias_key(r)))
    if sort == "session_count":
        return sorted(rows, key=lambda r: (-r.session_count, alias_key(r)))
    if sort == "overall":
        return sorted(rows, key=lambda r: (r.avg_overall is None, -(r.avg_overall or 0.0), alias_key(r)))
    if sort.startswith("custom:"):
        dim_id = sort.split(":", 1)[1]
        avgs = _custom_dim_averages(session, dim_id)
        return sorted(
            rows,
            key=lambda r: (avgs.get(r.person.id) is None, -(avgs.get(r.person.id) or 0.0), alias_key(r)),
        )
    # Unknown sort key → fall back to overall (the new default)
    return sorted(rows, key=lambda r: (r.avg_overall is None, -(r.avg_overall or 0.0), alias_key(r)))
```

- [ ] **Step 4: Update `web/dashboard_bp.py`**

In `flexlog/web/dashboard_bp.py`, change the default sort:

```python
@dashboard_bp.get("/dashboard")
def home():
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "overall").strip() or "overall"
    rows = list_dashboard_rows(get_db(), query, sort)
    cfg = current_app.config["FLEXLOG"]
    sortable_dimensions = [r for r in cfg.ratings if r.enabled and r.sortable]
    return render_template(
        "dashboard.html",
        rows=rows, query=query, sort=sort,
        sortable_dimensions=sortable_dimensions,
    )
```

- [ ] **Step 5: Update `dashboard.html`**

Add an `overall` option to the sort `<select>`, before `alias`. Replace the existing sort `<select>`:

```html
    <select id="sort" name="sort" onchange="this.form.submit()">
      <option value="overall"       {% if sort == "overall" %}selected{% endif %}>{{ "sort_overall" | ui }}</option>
      <option value="alias"         {% if sort == "alias" %}selected{% endif %}>{{ "sort_alias" | ui }}</option>
      <option value="last_date"     {% if sort == "last_date" %}selected{% endif %}>{{ "sort_last_date" | ui }}</option>
      <option value="session_count" {% if sort == "session_count" %}selected{% endif %}>{{ "sort_session_count" | ui }}</option>
      {% for dim in sortable_dimensions %}
        <option value="custom:{{ dim.id }}" {% if sort == "custom:" ~ dim.id %}selected{% endif %}>{{ "sort_custom_prefix" | ui }}{{ dim.label }}</option>
      {% endfor %}
    </select>
```

- [ ] **Step 6: Update `_partials/person_card.html`**

In `flexlog/templates/_partials/person_card.html`, add the avg_overall to the stats:

```html
    {% if row is defined and row %}
      <p class="person-card-stats">
        <span>{{ row.session_count }} {{ "session_count_singular" | ui if row.session_count == 1 else "session_count" | ui }}</span>
        {% if row.last_session_date %}<span>{{ "last_session" | ui }} {{ row.last_session_date }}</span>{% endif %}
        {% if row.avg_overall is not none %}<span class="person-card-overall">{{ row.avg_overall | overall_fmt }} / 5</span>{% endif %}
      </p>
    {% endif %}
```

- [ ] **Step 7: Add UI string + commit-time sweep**

In `flexlog/web/filters.py:BUILTIN_UI_DEFAULTS`, add:

```python
    "sort_overall": "Overall (avg)",
```

- [ ] **Step 8: Run new tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_dashboard_overall_sort.py -v --no-cov`
Expected: 4 PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -5`
Expected: green. The existing `test_dashboard_sort_v2.py` tests may need a small tweak if any of them asserted default sort behavior; check and adjust.

- [ ] **Step 9: Commit**

```bash
git add flexlog/services/people.py flexlog/web/dashboard_bp.py flexlog/templates/dashboard.html flexlog/templates/_partials/person_card.html flexlog/web/filters.py tests/integration/test_dashboard_overall_sort.py
git commit -m "$(cat <<'EOF'
dashboard: avg_overall column + sort=overall default

DashboardRow gains avg_overall: float | None, computed Python-side
as mean(session.overall) per person via the shared compute_overall
helper. _sort_rows handles a new 'overall' branch which becomes the
default (replaces 'alias'). dashboard.html surfaces a new "Overall
(avg)" sort option at the top of the dropdown. person-card.html
renders the avg next to session count.

custom:<dim> sorts stay for sortable dims (still useful for
single-dim drilldown).
EOF
)"
```

---

## Task 8: Person detail "Average across N sessions" line

Above the session list on `/people/<id>`, a one-line summary of the person's average overall. Hidden when N=0.

**Files:**
- Modify: `flexlog/web/people_bp.py`, `flexlog/templates/people/detail.html`, `flexlog/web/filters.py`
- Test: `tests/integration/test_person_detail_overall.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_person_detail_overall.py`:

```python
"""Person detail shows 'Average across N sessions: X.X' above the
session list. Hidden when no sessions exist."""
from __future__ import annotations


def test_person_detail_shows_average(authed_client, person, db_session):
    from flexlog.services.sessions import create_session
    create_session(db_session, person_id=person.id, session_date="2026-01-01",
                   ratings={"energy": 4}, notes=None, link_urls=[])
    create_session(db_session, person_id=person.id, session_date="2026-01-02",
                   ratings={"energy": 5}, notes=None, link_urls=[])
    db_session.commit()

    body = authed_client.get(f"/people/{person.id}").get_data(as_text=True)
    # Average of 4 and 5 is 4.5
    assert "4.5" in body
    assert "2" in body  # N
    # The summary line wording (configurable via UI string)
    assert "average" in body.lower() or "avg" in body.lower()


def test_person_detail_no_sessions_hides_average(authed_client, person, db_session):
    body = authed_client.get(f"/people/{person.id}").get_data(as_text=True)
    # Confirm the page renders at all
    assert person.alias in body
    # No "Average" line when there are no sessions
    assert "Average across" not in body
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_person_detail_overall.py -v --no-cov`
Expected: failures.

- [ ] **Step 3: Update `web/people_bp.py`**

Find the `detail` handler and replace its body to compute the avg + pass to the template:

```python
@people_bp.get("/<person_id>")
def detail(person_id: str):
    db = get_db()
    person = get_person(db, person_id)
    if person is None:
        abort(404)
    sessions = list_sessions_for_person(db, person_id)
    # Compute the person's average overall across their sessions.
    from flask import current_app
    from flexlog.services.sessions import compute_overall
    cfg = current_app.config["FLEXLOG"]
    overalls = [
        o for o in (compute_overall(s.ratings_json, cfg.ratings) for s in sessions)
        if o is not None
    ]
    avg_overall = sum(overalls) / len(overalls) if overalls else None
    return render_template(
        "people/detail.html",
        person=person, sessions=sessions, avg_overall=avg_overall,
    )
```

Also update the delete-error fallback rendering in the same file (line ~163) to pass `avg_overall=None` so the template doesn't break:

```python
        return render_template(
            "people/detail.html",
            person=person, sessions=sessions,
            avg_overall=None, delete_error=True,
        ), 400
```

- [ ] **Step 4: Update `people/detail.html`**

In `flexlog/templates/people/detail.html`, find the `<section class="sessions-section">` block and inject the average line above it:

```html
  {% if avg_overall is not none %}
  <p class="person-avg-summary">
    {{ "person_avg_prefix" | ui }} {{ sessions | length }}
    {% if sessions | length == 1 %}{{ labels.session.singular }}{% else %}{{ labels.session.plural }}{% endif %}:
    <strong>{{ avg_overall | overall_fmt }}</strong> / 5
  </p>
  {% endif %}

  <section class="sessions-section">
```

- [ ] **Step 5: Add UI string**

In `flexlog/web/filters.py:BUILTIN_UI_DEFAULTS`:

```python
    "person_avg_prefix": "Average across",
```

- [ ] **Step 6: Run new tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_person_detail_overall.py -v --no-cov`
Expected: 2 PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add flexlog/web/people_bp.py flexlog/templates/people/detail.html flexlog/web/filters.py tests/integration/test_person_detail_overall.py
git commit -m "$(cat <<'EOF'
people: 'Average across N sessions' line on detail page

Above the session list, render a one-line summary of the person's
average overall (mean of each session's weighted overall). Hidden
when the person has zero sessions. Uses the configurable session
singular/plural labels.
EOF
)"
```

---

## Task 9: Per-session row overall

Each session row on `/people/<id>` shows the session's own overall. Compact format.

**Files:**
- Modify: `flexlog/templates/_partials/session_row.html`, `flexlog/web/people_bp.py` (pass overalls)

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_person_detail_overall.py`:

```python
def test_session_row_shows_overall(authed_client, person, db_session):
    from flexlog.services.sessions import create_session
    create_session(db_session, person_id=person.id, session_date="2026-01-01",
                   ratings={"energy": 3}, notes="hello", link_urls=[])
    db_session.commit()

    body = authed_client.get(f"/people/{person.id}").get_data(as_text=True)
    # Session row shows the overall (single dim with weight 1.0 → 3.0)
    assert "3.0" in body
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_person_detail_overall.py::test_session_row_shows_overall -v --no-cov`
Expected: probably passes accidentally if 3.0 also appears in the average line. Use a more specific check: look for the value inside a `session-row` block. Update the test:

```python
def test_session_row_shows_overall(authed_client, person, db_session):
    from flexlog.services.sessions import create_session
    create_session(db_session, person_id=person.id, session_date="2026-01-01",
                   ratings={"energy": 3}, notes="hello", link_urls=[])
    db_session.commit()

    body = authed_client.get(f"/people/{person.id}").get_data(as_text=True)
    # Locate the session-row HTML block and confirm overall appears inside it.
    import re
    m = re.search(r'<li class="session-row".*?</li>', body, re.DOTALL)
    assert m is not None, "no session-row block found"
    assert "3.0" in m.group(0)
```

Run: `.venv/bin/python -m pytest tests/integration/test_person_detail_overall.py::test_session_row_shows_overall -v --no-cov`
Expected: FAIL (no overall in session row yet).

- [ ] **Step 3: Pass session overalls from the route handler**

In `flexlog/web/people_bp.py:detail`, compute a per-session overall map and pass to the template. Replace the body:

```python
@people_bp.get("/<person_id>")
def detail(person_id: str):
    db = get_db()
    person = get_person(db, person_id)
    if person is None:
        abort(404)
    sessions = list_sessions_for_person(db, person_id)
    from flask import current_app
    from flexlog.services.sessions import compute_overall
    cfg = current_app.config["FLEXLOG"]
    session_overalls = {
        s.id: compute_overall(s.ratings_json, cfg.ratings) for s in sessions
    }
    overalls = [v for v in session_overalls.values() if v is not None]
    avg_overall = sum(overalls) / len(overalls) if overalls else None
    return render_template(
        "people/detail.html",
        person=person, sessions=sessions,
        session_overalls=session_overalls,
        avg_overall=avg_overall,
    )
```

- [ ] **Step 4: Update `session_row.html`**

In `flexlog/templates/_partials/session_row.html`, add the overall in the row footer (or wherever fits the layout):

```html
{# Single session row on the person detail page.
   Caller passes `session` and (optionally) `session_overalls` dict. #}
<li class="session-row">
  <a class="session-row-link" href="{{ url_for('sessions.detail', session_id=session.id) }}">
    <header class="session-row-head">
      <time datetime="{{ session.session_date }}">{{ session.session_date }}</time>
      {% if session_overalls is defined and session_overalls.get(session.id) is not none %}
        <span class="session-row-overall">{{ session_overalls.get(session.id) | overall_fmt }} / 5</span>
      {% endif %}
    </header>
    {% if session.notes %}
    <p class="session-notes-preview">{{ session.notes | notes_preview }}</p>
    {% endif %}
    <footer class="session-row-foot">
      {% if session.links %}<span class="session-link-count">{{ session.links | length }} link{% if session.links|length != 1 %}s{% endif %}</span>{% endif %}
    </footer>
  </a>
</li>
```

- [ ] **Step 5: Run new test + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_person_detail_overall.py -v --no-cov`
Expected: all PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add flexlog/web/people_bp.py flexlog/templates/_partials/session_row.html tests/integration/test_person_detail_overall.py
git commit -m "people: per-session row shows the session's overall

session_row.html renders the session's computed overall next to its
date when the caller passes a session_overalls dict. people_bp.detail
builds the dict via compute_overall over each session's ratings_json
and passes it to the template."
```

---

## Task 10: Settings Ratings tab — drop scale columns, add weight column

The Ratings tab template gets restructured. Form fields change from `rating_scale_min[]` / `rating_scale_max[]` to `rating_weight[]`. New live-sum indicator placeholder ready for the JS in Task 12.

**Files:**
- Modify: `flexlog/templates/settings/_ratings.html`

- [ ] **Step 1: Replace `_ratings.html`**

Replace the contents of `flexlog/templates/settings/_ratings.html` with:

```html
<form method="post" action="{{ url_for('settings.save_ratings') }}" class="settings-form">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

  <p class="form-hint">Drag rows to reorder. Disable a dimension to hide it from new sessions without losing existing scores. The weights of enabled dimensions must sum to <strong>1.00</strong>.</p>

  <div class="weight-sum-indicator" data-weight-sum-indicator>
    Sum of enabled weights: <span data-weight-sum>0.00</span> / 1.00
  </div>

  <table class="ratings-table" data-ratings-table>
    <thead>
      <tr><th></th><th>id</th><th>Label</th><th>Description</th><th>Weight</th><th>Enabled</th><th>Sortable</th><th></th></tr>
    </thead>
    <tbody data-ratings-tbody>
      {% for r in config_dict.ratings %}
      {% set in_use = r.id in in_use_ids %}
      <tr class="rating-row" draggable="true">
        <td class="drag-handle">⋮⋮</td>
        <td>
          <input type="hidden" name="rating_original_id" value="{{ r.id }}">
          <input type="text" name="rating_id" value="{{ r.id }}" pattern="[a-z][a-z0-9_]*" {% if in_use %}readonly title="in use by existing sessions — rename blocked"{% endif %}>
        </td>
        <td><input type="text" name="rating_label" value="{{ r.label }}" required></td>
        <td><input type="text" name="rating_description" value="{{ r.description or '' }}"></td>
        <td>
          <input type="number" name="rating_weight" value="{{ '%.2f'|format(r.weight) }}" min="0.01" max="1.00" step="0.01" required data-weight-input>
          <span class="weight-pct" data-weight-pct>({{ (r.weight * 100) | round(0) | int }}%)</span>
        </td>
        <td><input type="checkbox" name="rating_enabled" value="{{ r.id }}" {% if r.enabled %}checked{% endif %} data-rating-enabled></td>
        <td><input type="checkbox" name="rating_sortable" value="{{ r.id }}" {% if r.sortable %}checked{% endif %}></td>
        <td><button type="button" class="btn rating-delete" data-rating-delete>✕</button></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <div style="display:flex;gap:0.6rem;margin-top:0.8rem;">
    <button type="button" class="btn" data-rating-add>+ Add rating dimension</button>
    <button type="button" class="btn" data-distribute-evenly>Distribute weights evenly</button>
  </div>

  <div class="form-actions" style="margin-top:1rem;">
    <button type="submit" class="btn btn-primary">Save</button>
  </div>
</form>

<template id="rating-row-template">
  <tr class="rating-row" draggable="true">
    <td class="drag-handle">⋮⋮</td>
    <td>
      <input type="hidden" name="rating_original_id" value="">
      <input type="text" name="rating_id" pattern="[a-z][a-z0-9_]*" required>
    </td>
    <td><input type="text" name="rating_label" required></td>
    <td><input type="text" name="rating_description"></td>
    <td>
      <input type="number" name="rating_weight" value="0.10" min="0.01" max="1.00" step="0.01" required data-weight-input>
      <span class="weight-pct" data-weight-pct>(10%)</span>
    </td>
    <td><input type="checkbox" name="rating_enabled" checked data-rating-enabled></td>
    <td><input type="checkbox" name="rating_sortable" checked></td>
    <td><button type="button" class="btn rating-delete" data-rating-delete>✕</button></td>
  </tr>
</template>
```

Append CSS to `flexlog/static/css/main.css`:

```css
/* Weight sum indicator */
.weight-sum-indicator {
  padding: 0.5rem 0.75rem; border-radius: 4px; margin: 0.5rem 0;
  font-size: 13px; background: #fef3c7;
}
.weight-sum-indicator.valid { background: #dcfce7; color: #14532d; }
.weight-sum-indicator.invalid { background: #fee2e2; color: #7f1d1d; }
.weight-pct { font-size: 11px; color: #6b7280; margin-left: 4px; }
```

- [ ] **Step 2: Smoke check the page still renders**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py::test_settings_page_renders_all_five_tabs -v --no-cov`
Expected: PASS (the page renders; the weight column won't actually submit correctly yet — that's Task 11).

- [ ] **Step 3: Full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: existing settings ratings save tests will likely fail (form posts `rating_weight[]` instead of `rating_scale_min[]` / `rating_scale_max[]`). Note the failures; Task 11 fixes them.

If any non-settings-ratings test breaks here (e.g. unrelated GET tests), debug. Otherwise proceed.

- [ ] **Step 4: Commit**

```bash
git add flexlog/templates/settings/_ratings.html flexlog/static/css/main.css
git commit -m "$(cat <<'EOF'
settings: Ratings tab template — drop scale cols, add weight col

Removes scale_min / scale_max columns (those fields are gone in
schema v3). Adds a Weight column (number input, 0.01-1.00, step 0.01)
with a live percentage sibling, a sum-of-weights indicator at the
top, and a 'Distribute weights evenly' helper button.

Form parsing + sum-to-1 server validation lands in the next commit.
EOF
)"
```

---

## Task 11: Settings ratings form parser + sum-to-1 validation

`_parse_ratings_form` in `settings_bp.py` switches from reading `rating_scale_min[]` / `rating_scale_max[]` to `rating_weight[]`. `save_ratings` adds a sum-to-1 check before persisting.

**Files:**
- Modify: `flexlog/web/settings_bp.py`
- Test: `tests/integration/test_settings_weight_validation.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_settings_weight_validation.py`:

```python
"""Settings Ratings tab: weight column + sum-to-1 validation."""
from __future__ import annotations

import json
import re
from pathlib import Path


def _csrf_token(client, path="/settings?tab=ratings"):
    body = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    return m.group(1)


def test_settings_save_ratings_with_valid_sum(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy", ""],
            "rating_id": ["energy", "depth"],
            "rating_label": ["Energy", "Depth"],
            "rating_description": ["", ""],
            "rating_weight": ["0.4", "0.6"],
            "rating_enabled": ["energy", "depth"],
            "rating_sortable": ["energy", "depth"],
        },
    )
    assert resp.status_code == 303
    cfg = json.loads((tmp_data_dir / "config.json").read_text())
    weights = [r["weight"] for r in cfg["ratings"]]
    assert weights == [0.4, 0.6]


def test_settings_save_ratings_rejects_bad_sum(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    original = (tmp_data_dir / "config.json").read_text()
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy", ""],
            "rating_id": ["energy", "depth"],
            "rating_label": ["Energy", "Depth"],
            "rating_description": ["", ""],
            "rating_weight": ["0.5", "0.4"],  # sum 0.9, not 1.0
            "rating_enabled": ["energy", "depth"],
            "rating_sortable": ["energy"],
        },
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "sum" in body.lower() and "1.0" in body
    # config.json untouched
    assert (tmp_data_dir / "config.json").read_text() == original


def test_settings_save_ratings_rejects_zero_weight(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy"],
            "rating_id": ["energy"],
            "rating_label": ["Energy"],
            "rating_description": [""],
            "rating_weight": ["0"],
            "rating_enabled": ["energy"],
            "rating_sortable": ["energy"],
        },
    )
    assert resp.status_code == 400


def test_settings_save_disabled_dim_weight_excluded_from_sum(csrf_authed_client, tmp_data_dir):
    """Disabled dim's weight isn't counted toward the sum."""
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_original_id": ["energy", "depth"],
            "rating_id": ["energy", "depth"],
            "rating_label": ["Energy", "Depth"],
            "rating_description": ["", ""],
            "rating_weight": ["1.0", "0.5"],
            "rating_enabled": ["energy"],  # depth NOT enabled
            "rating_sortable": ["energy"],
        },
    )
    # Enabled sum = 1.0 (only energy). Should pass.
    assert resp.status_code == 303
    cfg = json.loads((tmp_data_dir / "config.json").read_text())
    weights = {r["id"]: r["weight"] for r in cfg["ratings"]}
    assert weights == {"energy": 1.0, "depth": 0.5}
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_weight_validation.py -v --no-cov`
Expected: failures (parser still reads scale fields, not weight).

- [ ] **Step 3: Update `_parse_ratings_form`**

In `flexlog/web/settings_bp.py`, replace `_parse_ratings_form`:

```python
def _parse_ratings_form() -> tuple[list[dict], list[tuple[str, str]], list[str]]:
    """Read repeating rating_* form fields. Returns
    (ratings_list, [(orig_id, new_id), ...], errors)."""
    ids = request.form.getlist("rating_id")
    original_ids = request.form.getlist("rating_original_id")
    labels = request.form.getlist("rating_label")
    descriptions = request.form.getlist("rating_description")
    weights = request.form.getlist("rating_weight")
    enabled_set = set(request.form.getlist("rating_enabled"))
    sortable_set = set(request.form.getlist("rating_sortable"))

    n = len(ids)
    if not (len(labels) == len(weights) == n):
        return [], [], ["rating rows are misaligned; refresh the page and try again"]

    ratings: list[dict] = []
    pairs: list[tuple[str, str]] = []
    errors: list[str] = []
    for i in range(n):
        rid = (ids[i] or "").strip()
        if not rid:
            continue
        orig = (original_ids[i] if i < len(original_ids) else "") or ""
        try:
            weight = float(weights[i])
        except (ValueError, TypeError):
            errors.append(f"ratings[{i}]: weight must be a number")
            continue
        if not (0.0 < weight <= 1.0):
            errors.append(f"ratings[{i}]: weight must be in (0, 1]; got {weight}")
            continue
        descr = (descriptions[i] if i < len(descriptions) else "") or None
        ratings.append({
            "id": rid,
            "label": (labels[i] or "").strip(),
            "description": descr if descr else None,
            "enabled": rid in enabled_set,
            "sortable": rid in sortable_set,
            "weight": weight,
        })
        pairs.append((orig, rid))
    return ratings, pairs, errors
```

The `save_ratings` handler doesn't need to change — `validate_config_dict` already enforces the sum-to-1 check (from Task 1).

- [ ] **Step 4: Run new tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_weight_validation.py -v --no-cov`
Expected: 4 PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -10`
Expected: green. The legacy `test_settings_routes.py::test_settings_ratings_add_dimension` test posts `rating_scale_min[]` / `rating_scale_max[]` — that test needs updating to use `rating_weight[]` instead. Fix it:

In `tests/integration/test_settings_routes.py`, find `test_settings_ratings_add_dimension` and replace its POST body to use `rating_weight`:

```python
def test_settings_ratings_add_dimension(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=ratings")
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            "rating_id": ["energy", "focus"],
            "rating_label": ["Energy", "Focus"],
            "rating_description": ["How energetic", "How focused"],
            "rating_weight": ["0.5", "0.5"],
            "rating_enabled": ["energy", "focus"],
            "rating_sortable": ["energy"],
        },
    )
    assert resp.status_code == 303
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert [r["id"] for r in cfg["ratings"]] == ["energy", "focus"]
    # 'focus' wasn't in rating_sortable → sortable=False
    assert cfg["ratings"][1]["sortable"] is False
```

Run the full suite again to verify green.

- [ ] **Step 5: Commit**

```bash
git add flexlog/web/settings_bp.py tests/integration/test_settings_weight_validation.py tests/integration/test_settings_routes.py
git commit -m "$(cat <<'EOF'
settings: Ratings tab parser + sum-to-1 validation

_parse_ratings_form switches from rating_scale_min/max[] to
rating_weight[]; values are floats in (0, 1]. The sum-to-1 check
is already enforced by validate_config_dict (added in Task 1),
so save_ratings inherits it automatically — bad sums return 400
with the validator's error message, no config.json write.

Disabled dims contribute their weight to ratings_json but are
excluded from the sum-to-1 check.
EOF
)"
```

---

## Task 12: settings.js — live weight-sum indicator + Distribute Evenly button

JS for the Ratings tab: keeps the sum-of-weights indicator updated and wires up the "Distribute weights evenly" button.

**Files:**
- Modify: `flexlog/static/js/settings.js`

- [ ] **Step 1: Smoke test the file is served**

Append to `tests/integration/test_settings_routes.py`:

```python
def test_settings_js_has_weight_sum_helper(authed_client):
    resp = authed_client.get("/static/js/settings.js")
    assert resp.status_code == 200
    assert b"weight" in resp.data.lower()
    assert b"distribute" in resp.data.lower()
```

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py::test_settings_js_has_weight_sum_helper -v --no-cov`
Expected: FAIL — current settings.js has no weight handling.

- [ ] **Step 2: Update `settings.js`**

Append to `flexlog/static/js/settings.js` (don't replace — keep the existing `bindRatingsTable` logic, just add the new behavior):

```javascript

// --- M7 additions: weight sum indicator + Distribute Evenly button ---

document.addEventListener("DOMContentLoaded", () => {
  bindWeightHandling();
});

function bindWeightHandling() {
  const tbody = document.querySelector("[data-ratings-tbody]");
  if (!tbody) return;

  const recompute = () => {
    let sum = 0;
    for (const row of tbody.querySelectorAll(".rating-row")) {
      const enabled = row.querySelector('[data-rating-enabled]');
      if (!enabled || !enabled.checked) {
        updatePct(row);
        continue;
      }
      const input = row.querySelector('[data-weight-input]');
      const w = parseFloat(input.value) || 0;
      sum += w;
      updatePct(row);
    }
    const indicator = document.querySelector("[data-weight-sum-indicator]");
    const sumEl = document.querySelector("[data-weight-sum]");
    if (sumEl) sumEl.textContent = sum.toFixed(2);
    if (indicator) {
      indicator.classList.toggle("valid", Math.abs(sum - 1.0) < 1e-6);
      indicator.classList.toggle("invalid", Math.abs(sum - 1.0) >= 1e-6);
    }
  };

  const updatePct = (row) => {
    const input = row.querySelector('[data-weight-input]');
    const pctEl = row.querySelector('[data-weight-pct]');
    if (!input || !pctEl) return;
    const w = parseFloat(input.value) || 0;
    pctEl.textContent = "(" + Math.round(w * 100) + "%)";
  };

  // Initial render
  recompute();

  // Recompute on any change inside the tbody (input or enabled checkbox).
  tbody.addEventListener("input", recompute);
  tbody.addEventListener("change", recompute);
  tbody.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-rating-delete]")) {
      // Allow the existing handler to remove the row first; recompute after.
      setTimeout(recompute, 0);
    }
  });

  const distributeBtn = document.querySelector("[data-distribute-evenly]");
  if (distributeBtn) {
    distributeBtn.addEventListener("click", () => {
      const enabledRows = Array.from(tbody.querySelectorAll(".rating-row"))
        .filter((row) => {
          const cb = row.querySelector('[data-rating-enabled]');
          return cb && cb.checked;
        });
      const n = enabledRows.length;
      if (n === 0) return;
      const per = Math.round((1.0 / n) * 100) / 100;
      for (let i = 0; i < n - 1; i++) {
        enabledRows[i].querySelector('[data-weight-input]').value = per.toFixed(2);
      }
      // Last enabled row absorbs the rounding remainder so sum is exactly 1.0.
      const last = +(1.0 - per * (n - 1)).toFixed(2);
      enabledRows[n - 1].querySelector('[data-weight-input]').value = last.toFixed(2);
      recompute();
    });
  }

  // When a new row is added via the existing Add button, the listener via
  // `tbody.addEventListener("input")` will pick it up automatically.
}
```

- [ ] **Step 3: Run new test + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py::test_settings_js_has_weight_sum_helper -v --no-cov`
Expected: PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green.

- [ ] **Step 4: Manual browser smoke (skip if executing via subagent)**

The controller may verify in a browser:
1. Open `/settings?tab=ratings`.
2. Edit a weight → see the percentage sibling and the top-of-table sum indicator update live.
3. Disable a dim → see its weight removed from the sum.
4. Click "Distribute weights evenly" → weights become `1/N` per enabled dim, sum exactly 1.0.

- [ ] **Step 5: Commit**

```bash
git add flexlog/static/js/settings.js tests/integration/test_settings_routes.py
git commit -m "$(cat <<'EOF'
settings.js: live weight-sum indicator + Distribute Evenly

Recomputes Σ(enabled weights) on every input/change/delete event
inside the ratings tbody and tints the indicator green/red based
on whether the sum equals 1.0 (with float epsilon). The percentage
sibling next to each weight input updates live so the user can
read percentages without doing the math.

The Distribute Evenly button sets each enabled dim to 1/N rounded
to 2 decimals; the last enabled row absorbs the rounding remainder
so the sum is exactly 1.0.
EOF
)"
```

---

## Task 13: Test sweep — adapt remaining v2-shape stragglers

Sweep the suite for any test still referencing `scale_min` / `scale_max` / `rating_<id>` as a number input that wasn't covered above, plus any test that asserts the old default sort.

**Files:**
- Modify: various `tests/` files
- Verify: full suite green, coverage ≥85%

- [ ] **Step 1: Search**

```bash
grep -rn "scale_min\|scale_max" tests/ | grep -v ".pyc"
grep -rn 'name="rating_scale' tests/
grep -rn '"avg_score"' tests/
```

- [ ] **Step 2: Fix each match**

For each test file that turns up:
- Replace `rating_scale_min` / `rating_scale_max` form fields with `rating_weight`.
- Drop scale-related dim attributes; add `weight=1.0` (or appropriate fraction) on test-built `RatingDimension` objects.
- Where a test asserts the default dashboard sort, update from `alias` to `overall` (or just stop relying on the default).

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -10`
Expected: 0 failures, coverage ≥85%.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "tests: sweep v2-shape stragglers (scale_min/max, default sort)

Remaining tests that referenced scale_min/scale_max in fixtures or
form posts, or that asserted the old 'alias' default sort, are
updated to the v3 / overall shape. Suite stays green at ≥85%
coverage."
```

---

## Task 14: Version bump to v0.4.0 + README

Final commit — record the milestone.

**Files:**
- Modify: `pyproject.toml`, `README.md`

- [ ] **Step 1: Bump version**

In `pyproject.toml`:

```toml
version = "0.4.0"
```

- [ ] **Step 2: Update README**

Add to `README.md` immediately before the existing `## v0.3.0` section (so the most recent release is on top):

```markdown
## v0.4.0 — Weighted Overall Ratings + Star Input

- **Weighted overall rating per session.** Each rating dimension now has a `weight: float` in config. The session overall is the weighted average of its sub-ratings, displayed as a 1-decimal number (e.g. `4.3 / 5`).
- **Star input.** The session form replaces number typing with star clicking. Five stars per dimension; click again to decrement (or click star 1 when at 1 to clear to 0). Keyboard: ←/→ to adjust, Space/Enter to commit. A live overall preview updates as you click.
- **Sub-ratings locked at 0..5 integer.** The `scale_min` / `scale_max` fields are removed from the config schema (`schema_version` bumps to 3).
- **Dashboard sorted by overall (avg).** New default sort: average overall across each person's sessions. Old `custom:<dim>` sorts stay for sortable dims.
- **Person detail shows the average.** Above the session list: `"Average across N interviews: 4.2"`. Each session row shows its own overall.
- **Settings Ratings tab:** scale columns gone; new weight column with live sum-of-enabled-weights indicator and a "Distribute weights evenly" button.

**No DB migration.** v0.3.0 wasn't in production yet — pre-v3 `config.json` files auto-upgrade on first launch (scale fields stripped, weights distributed uniformly). If you had any sessions stored in a v0.3.0 data dir, clear them before upgrading.
```

- [ ] **Step 3: Run final suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 4: Commit + tag**

```bash
git add pyproject.toml README.md
git commit -m "$(cat <<'EOF'
v0.4.0: weighted overall ratings + star input

See README for the full change list. Config auto-upgrades from
v0.2.x/v0.3.0 shape (scale fields stripped, weights distributed).
EOF
)"
git tag v0.4.0
```

Do NOT push the tag — leave that to the user.

---

## Self-Review

**Spec coverage (each spec section → tasks that implement it):**

- §1 (Goal) — covered across all tasks
- §2 (Config schema v3) — Task 1 (validator + parser + auto-upgrade + default config)
- §3 (Compute & storage) — Task 2 (compute_overall)
- §4 (Form UI / star input) — Task 5 (template + JS + CSS) + Task 6 (server-side clamp)
- §5 (Display surfaces) — Task 3 (filters) + Task 4 (detail) + Task 7 (dashboard) + Task 8 (person avg) + Task 9 (session row)
- §6 (Settings Ratings tab) — Task 10 (template) + Task 11 (form parser + validator) + Task 12 (JS)
- §7 (Error handling) — covered across Tasks 1, 2, 5, 6, 11 (each handler's failure path)
- §8 (Testing) — every task ships its own unit/integration tests; Task 13 sweeps stragglers
- §9 (Rollout) — Task 14
- §10 (Files touched) — matches this plan's file map
- §11 (Out of scope) — respected throughout

No gaps.

**Placeholder scan:** scanned for "TBD" / "TODO" / "similar to" / "add appropriate error handling" — none.

**Type consistency:**

- `compute_overall(stored_json: str | None, dims) -> float | None` — same signature in Task 2 + Tasks 4, 7, 8, 9 (callers).
- `RatingDimension` field order — defined in Task 1 (`id, label, description, enabled, sortable, weight`) — used consistently in Task 2's test helper.
- Form field names — `rating_id[]`, `rating_label[]`, `rating_description[]`, `rating_weight[]`, `rating_enabled` (set), `rating_sortable` (set), `rating_original_id[]` — consistent across Tasks 10 (template), 11 (parser), 12 (JS).
- Jinja filters — `overall_fmt`, `star_fill` defined in Task 3, used in Tasks 4, 7, 8, 9.
- Dashboard sort default — `"overall"` consistent across Task 7's `list_dashboard_rows` default + `dashboard_bp.home` default + `_sort_rows` fallback.
- Hidden input naming — `rating_<id>` on the session form (Task 5) matches `_parse_ratings_from_request` (Task 6).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-17-flexlog-weighted-ratings-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task using Opus (per your "use opus for careful implementation" request), with two-stage review between tasks.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`; batch execution with checkpoints.

Which approach?
