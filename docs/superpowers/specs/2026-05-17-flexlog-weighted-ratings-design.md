# M7 — Weighted Overall Ratings + Star Input

**Status:** Design (draft, awaiting user review)
**Date:** 2026-05-17
**Version target:** v0.4.0
**Branches affected:** main

---

## 1. Goal

Refactor the rating system so a session's **overall rating** is a computed weighted average of its sub-ratings. Replace number-typing input with star clicking. Surface the overall on the dashboard, person detail, and session detail.

Implementation pillars:
1. Each rating dimension in `config.json` gains a `weight: float`. The weights of *enabled* dimensions must sum to 1.0.
2. Sub-rating values are locked at integer 0..5. The configurable `scale_min` / `scale_max` fields are removed from the config schema.
3. The session "overall" is never stored — always computed on read from `ratings_json` + the current weights. This keeps it reactive when the user re-balances weights in Settings.
4. Star-clicker UI replaces `<input type="number">`. Sub-ratings are required (every enabled dim renders five stars; 0 is a valid score via "clear the last lit star").
5. Person-level overall = simple arithmetic mean of that person's session overalls.

**No DB migration.** v0.3.0 isn't in production yet; users clear their data directory before upgrading. The config file's `schema_version` bumps to 3 and an auto-upgrade strips removed fields + distributes uniform default weights for any v2 config encountered.

## 2. Config schema v3

### Shape

```json
{
  "schema_version": 3,
  "app": { "name": "...", ... },
  "ratings": [
    {
      "id": "clarity",
      "label": "Clarity",
      "description": "How clear and articulate",
      "enabled": true,
      "sortable": true,
      "weight": 0.5
    },
    {
      "id": "depth",
      "label": "Depth",
      "description": "Substance of the material",
      "enabled": true,
      "sortable": true,
      "weight": 0.3
    },
    {
      "id": "energy",
      "label": "Energy",
      "description": "How energetic the session felt",
      "enabled": true,
      "sortable": false,
      "weight": 0.2
    }
  ],
  "ui_strings": { ... },
  "limits": { ... }
}
```

### Changes to `RatingDimension` dataclass

| Field | v2 → v3 status | Notes |
|---|---|---|
| `id` | unchanged | snake_case, immutable once used by sessions |
| `label` | unchanged | display name |
| `description` | unchanged | optional |
| `scale_min` | **removed** | locked at 0 |
| `scale_max` | **removed** | locked at 5 |
| `enabled` | unchanged | controls inclusion in form + weight-sum check |
| `sortable` | unchanged | drives dashboard per-dim sort dropdown |
| `weight` | **new** | required `float` in `(0.0, 1.0]` |

### Validation rules

- `weight` must be a `float` (or `int` coerced to float at parse time) in `(0.0, 1.0]`. Reject `0.0`, negatives, and `> 1.0`.
- Sum of `weight` across **enabled** dimensions must equal `1.0 ± 1e-6` (float epsilon). Error wording: `"weights of enabled rating dimensions must sum to 1.0; got X.XXX"`.
- Disabled dimensions retain a `weight` value in config (so the user can re-enable without re-entering it) but their weight does NOT count toward the sum.
- If a v3 config submits `scale_min` or `scale_max` keys (only reachable via Raw JSON tab), reject with `"scale fields removed in schema_version 3; sub-ratings are 0..5"`.

### Default bootstrap config

A fresh install creates one example dimension:

```json
{
  "id": "energy",
  "label": "Energy",
  "description": "How energetic the session felt",
  "enabled": true,
  "sortable": true,
  "weight": 1.0
}
```

(A single enabled dim sums to 1.0 trivially.)

### v2 → v3 auto-upgrade

On app launch, if `config.json` has `schema_version == 2`:

1. For each rating dim, drop `scale_min` and `scale_max` keys.
2. Compute `N = number of enabled dims`.
3. For each enabled dim that lacks a `weight`, set `weight = round(1/N, 2)`. The **last** enabled dim absorbs the rounding remainder so the sum is exactly 1.0.
4. For each disabled dim that lacks a `weight`, set `weight = 0.01` (placeholder; doesn't affect the sum).
5. Bump `schema_version` to 3.
6. Atomic rewrite to disk (same `O_EXCL` 0600 + fsync + rename pattern as v1→v2).

Already-v3 configs: no-op.

## 3. Compute & storage

### Session overall

```
overall(session) = Σ (sub_rating_value × weight)
                   over each enabled dim
```

Implementation: `flexlog/services/sessions.py:compute_overall(stored_json: str | None, enabled_dims: list[RatingDimension]) -> float | None`.

- Returns `None` if `stored_json` is empty / malformed / not a dict.
- Returns `None` if no enabled dims exist (no dims to weigh).
- For each enabled dim, look up `stored_json[dim.id]`. If missing, treat as `0` (per agreed model — new sessions are required to set every dim, so missing values shouldn't occur except for legacy/manual data).
- Cast values to `float`, multiply by `dim.weight`, sum. Denominator is implicitly 1.0 (weights sum to 1 by config invariant).

### Person overall

`mean(session.overall for session in person.sessions if overall is not None)`. Returns `None` if the person has no sessions or all their sessions have undefined overalls (which would only happen with broken data).

### Storage unchanged

- `Session.ratings_json` continues to hold `{id: int, ...}` — sub-ratings only.
- The overall is **never persisted**. Reason: weights change in config; the displayed overall must reflect current weights, so we recompute on every read. Cost is negligible (≤6 multiplications per session).
- No DB schema change. `PRAGMA user_version` stays at 2.

### Type discipline

- Sub-rating values: `int`, validated to `0 ≤ v ≤ 5` in the route handler. Out-of-range values get clamped silently to the closest endpoint (defensive — JS shouldn't send them).
- Overall: `float`, formatted to 1 decimal at the template boundary via a new Jinja filter `overall_fmt`.

## 4. Form UI (star input)

### Layout per dimension

```
Clarity     ★ ★ ★ ★ ☆     4 / 5
Depth       ★ ★ ★ ★ ★     5 / 5
Energy      ★ ★ ★ ☆ ☆     3 / 5
─────────────────────────────────
Overall (preview): 4.3
```

### Markup pattern (per dim)

```html
<div class="rating-input" data-dim-id="clarity" data-weight="0.5">
  <label>Clarity</label>
  <div class="star-row" role="radiogroup" aria-label="Clarity rating">
    <button type="button" class="star" data-value="1" aria-label="1 star">★</button>
    <button type="button" class="star" data-value="2" aria-label="2 stars">★</button>
    <button type="button" class="star" data-value="3" aria-label="3 stars">★</button>
    <button type="button" class="star" data-value="4" aria-label="4 stars">★</button>
    <button type="button" class="star" data-value="5" aria-label="5 stars">★</button>
  </div>
  <span class="value-readout">0 / 5</span>
  <input type="hidden" name="rating_clarity" value="0">
</div>
```

### Interaction (JS in `flexlog/static/js/rating_stars.js`)

- Click star N: set value to N. Fill stars 1..N as ★ (filled), N+1..5 as ☆ (outline).
- Click the rightmost lit star (i.e., click N when current value is N): set value to N-1.
- Click star 1 when value is 1: set value to 0 (all stars empty).
- Hover preview: highlight stars 1..N on hover; revert on mouseleave (no commit until click).
- Keyboard: when a star has focus, ← decrements, → increments, Space/Enter commits the focused position. Tab moves between dims.
- The hidden `<input>` is the only thing the form submits. Its value updates on every commit. `aria-pressed="true"` on lit stars, `"false"` on unlit.

### Live overall preview

A single `<output id="overall-preview">` below the ratings fieldset. JS reads each row's `data-weight` and `<input>` value on every change, computes `Σ(value × weight)`, formats to 1 decimal, writes to the output. The server computes its own authoritative overall on save; the preview is for UX only.

### Required vs. missing

All enabled dims render. The hidden input defaults to `0`, which is a valid score. No client-side "required" validation needed; every submit carries a complete set of `rating_<id>` values (all integers in `[0, 5]`).

### Accessibility

- Each row is a `role="radiogroup"` with `aria-label="<dim label> rating"`.
- Stars have `aria-pressed="true|false"`.
- Hidden inputs mirror values for screen readers.
- Focus styling via CSS `.star:focus-visible` (high-contrast outline).

## 5. Display surfaces

The overall is shown on four surfaces:

### Session detail (`/sessions/<id>`)

Large overall at the top of the Ratings section, sub-rating star rows below.

```html
<section class="ratings-display">
  <h3>Ratings</h3>
  {% if overall is not none %}
  <div class="overall-display">
    <span class="overall-value">{{ overall | overall_fmt }}</span>
    <span class="overall-scale">/ 5 overall</span>
    <span class="overall-method">(weighted avg)</span>
  </div>
  {% endif %}
  <ul class="sub-ratings">
    {% for dim, value in current_ratings %}
      <li>
        <span class="dim-label">{{ dim.label }}</span>
        <span class="stars">{{ value | star_fill }}</span>
        <span class="dim-meta">{{ value }} (weight {{ (dim.weight * 100) | round(0) | int }}%)</span>
      </li>
    {% endfor %}
  </ul>
</section>
```

### Dashboard (`/`)

- `DashboardRow` gains `avg_overall: float | None`.
- `list_dashboard_rows` walks each person's sessions, computes overall per session, averages.
- New sort key `overall` (lowest priority by alias tie-break). Becomes the **default sort** (replaces `alias` as default).
- Per-dim `custom:<id>` sorts stay for `sortable=True` dims (still useful).
- Dashboard template adds a column showing `row.avg_overall | overall_fmt` or em-dash for `None`.

### Person detail (`/people/<id>`)

Above the session list, a single line: `"Average across {{ n }} {{ session_plural }}: {{ avg | overall_fmt }}"`. Hidden when `n == 0`.

### Per-session row (anywhere session rows render)

A new column or inline element: `{{ session_overall | overall_fmt }}`. Compact format.

### Rendering helpers

Two new Jinja filters in `flexlog/web/filters.py`:

- `overall_fmt(value: float | None) -> str` — formats float to 1 decimal (`"%.1f"`); returns `""` for `None`.
- `star_fill(value: int) -> str` — returns `"★" * value + "☆" * (5 - value)` for inline rendering.

## 6. Settings UI (Ratings tab)

### Column changes

| Column | v2 | v3 |
|---|---|---|
| id | text input | unchanged |
| Label | text input | unchanged |
| Description | text input | unchanged |
| **scale_min** | number input 0-99 | **removed** |
| **scale_max** | number input 1-100 | **removed** |
| Enabled | checkbox | unchanged |
| Sortable | checkbox | unchanged |
| **Weight** | — | **new**: `<input type="number" step="0.01" min="0" max="1">` + live `<span>` showing `(= NN%)` updated by JS |

### Live sum indicator

At the top of the table:

```
Sum of enabled weights: 0.95 / 1.00     [color: red]
Sum of enabled weights: 1.00 / 1.00 ✓   [color: green]
```

JS updates on every weight-input change AND every enabled-checkbox toggle.

### "Distribute weights evenly" button

A button at the bottom of the table. On click, sets each enabled dim's weight to `round(1/N_enabled, 2)`; the last enabled dim absorbs the rounding remainder so the sum is exactly 1.0. Updates the live sum indicator to green.

### Server validation on save

- Parse `rating_weight[]` parallel to `rating_id[]` etc.
- Each weight: `float` in `(0, 1]`. Reject otherwise.
- Sum of weights for `rating_enabled` items (set in form): `== 1.0 ± 1e-6`. Reject otherwise.
- Other validation (id format, label non-empty, etc.) unchanged.
- Errors re-render the tab with field-level messages.

### Raw JSON tab

Unchanged structurally. Saving raw JSON with `scale_min` / `scale_max` keys present returns the "scale fields removed in schema_version 3" error. Saving with missing `schema_version` or `schema_version != 3` returns the existing schema_version error.

## 7. Error handling

| Scenario | Behavior |
|---|---|
| Form POSTs `rating_<id>` outside `[0, 5]` | Server clamps silently to nearest endpoint. No flash. |
| Form POSTs an unknown `rating_<id>` (id not in config) | Server ignores it (existing behavior). |
| Settings save with weights not summing to 1.0 | 400 + re-render Ratings tab with field error + red sum indicator. |
| Settings save with negative or zero weight | 400 + field-level error on the bad row. |
| Settings save with `scale_min` / `scale_max` keys (via Raw JSON tab) | 400 + `"scale fields removed in schema_version 3"`. |
| Config auto-upgrade fails (file unwritable) | App boot raises with a friendly setup-error page (existing `MigrationError` handler covers this — extend it to catch `ConfigError` from the upgrade path). |
| Session's `ratings_json` has values > 5 (legacy / hand-edited) | `compute_overall` clamps internally to `5` for the multiplication; doesn't error. |
| Session has no `ratings_json` or empty dict | `compute_overall` returns `None`; templates render `—`. |

## 8. Testing strategy

≥85% coverage gate stays enforced (`pyproject.toml --cov-fail-under=85`).

### New unit tests

- `tests/unit/test_compute_overall.py` — weighted-average math, empty stored_json, single-dim shortcut, integer→float overall, value-clamp for out-of-range stored values.
- `tests/unit/test_weight_validation.py` — sum-to-1 with float epsilon, weight range, disabled dims excluded from sum.
- `tests/unit/test_config_v2_to_v3_autoupgrade.py` — v2→v3 auto-upgrade (weight distribution with rounding-remainder, scale fields stripped, schema_version bumped, atomic write semantics).
- `tests/unit/test_overall_fmt_filter.py` — formats `None` as empty, floats to 1 decimal, integer-valued floats render as `4.0`.

### New integration tests

- `tests/integration/test_session_form_stars.py` — POST `rating_<id>` integers 0–5 → server stores them in `ratings_json` → detail page renders the right overall.
- `tests/integration/test_dashboard_overall_sort.py` — `?sort=overall` orders people by their average session overall, NULLs (no sessions) last; default sort is now `overall`.
- `tests/integration/test_person_detail_overall.py` — person detail shows "Average across N sessions: X.X" line and per-session rows show their overall.
- `tests/integration/test_settings_weight_validation.py` — Ratings tab save rejects bad sums (0.95, 1.05) and accepts good (1.00); "Distribute evenly" POST yields `1/N`-rounded values that sum to exactly 1.0.

### Adapted tests

Tests that reference `scale_min` / `scale_max` or `<input type="number" name="rating_<id>">` need updates. Sweep similar to M5/M6.

## 9. Rollout

- Ships as **v0.4.0**. Bump `pyproject.toml`.
- README adds a v0.4.0 section: weighted overall ratings, star input, no data migration, config auto-upgrades v2 → v3 on first launch.
- Tag `v0.4.0` after the suite is green.

## 10. Files touched (summary)

**Modified:**
- `flexlog/config_loader.py` — `RatingDimension` (add weight, drop scale_min/max), `_parse_ratings`, `validate_config_dict` (sum-to-1), `DEFAULT_CONFIG_JSON` (single dim with weight 1.0), `load_or_bootstrap` (extend v1 upgrade path to also handle v2→v3).
- `flexlog/services/sessions.py` — new `compute_overall`, drop scale-related validation from `_parse_ratings_from_request` callers (handled server-side via int clamp).
- `flexlog/services/people.py` — `DashboardRow` gains `avg_overall`; `list_dashboard_rows` computes it; `_sort_rows` adds `overall` branch (becomes default).
- `flexlog/web/dashboard_bp.py` — default sort changes from `alias` to `overall`.
- `flexlog/web/sessions_bp.py` — handlers pass `compute_overall(...)` result to detail/edit templates as `overall` context var.
- `flexlog/web/people_bp.py` — person detail handler computes avg_overall, passes to template.
- `flexlog/web/settings_bp.py` — `_parse_ratings_form` reads `rating_weight[]`; validation adds sum-to-1 check.
- `flexlog/web/filters.py` — register `overall_fmt` and `star_fill` filters.
- `flexlog/templates/sessions/_form_body.html` — replace `<input type="number">` rating block with star-row markup.
- `flexlog/templates/sessions/detail.html` — overall-display at top of ratings section, star rendering on sub-ratings.
- `flexlog/templates/dashboard.html` — overall column + sort option.
- `flexlog/templates/people/detail.html` — "Average across N sessions" line, per-session row overall column.
- `flexlog/templates/settings/_ratings.html` — drop scale columns, add weight column + sum indicator + "Distribute evenly" button.
- `flexlog/static/css/main.css` — `.star-row`, `.star.lit`, `.star:focus-visible`, `.overall-display`, `.weight-sum-indicator`.
- `pyproject.toml` — version bump to 0.4.0.

**New:**
- `flexlog/static/js/rating_stars.js` — star input behavior + live overall preview.
- `tests/unit/test_compute_overall.py`, `tests/unit/test_weight_validation.py`, `tests/unit/test_config_v2_to_v3_autoupgrade.py`, `tests/unit/test_overall_fmt_filter.py`.
- `tests/integration/test_session_form_stars.py`, `tests/integration/test_dashboard_overall_sort.py`, `tests/integration/test_person_detail_overall.py`, `tests/integration/test_settings_weight_validation.py`.

**Deleted:** none.

## 11. Out of scope

- Half-star input (sub-ratings stay integer-only).
- Persisting the overall in the DB (always computed on read; weights change in config and the overall should reflect them).
- Bulk editing weights from the dashboard (Settings page is the only entry point).
- Per-person weight overrides (weights are global).
- DB schema migration (DB schema unchanged; `PRAGMA user_version` stays at 2).

## 12. Open questions

None. All decisions are pinned.
