# M6 — Settings UI + Session-form UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `overall_score` with fully config-driven rating dimensions, add a `/settings` UI with five tabs to edit `config.json`, switch session-form media uploads to a progressive AJAX flow, revamp the links UI as single-textbox-plus-Add, and reorder the session-detail page.

**Architecture:** Schema rename (`custom_ratings_json` → `ratings_json`) + drop hardcoded `overall_score`, gated by an idempotent migration keyed on SQLite `PRAGMA user_version`. Settings page is one Flask blueprint with five POST handlers feeding into a new `validate_config_dict` validator. Uploads happen via two new AJAX endpoints in a dedicated `upload_bp.py`; the form tracks `file_key`s in hidden inputs and the Save handler only links rows.

**Tech Stack:** Flask 3.x, SQLAlchemy 2.x (SQLCipher-backed), Flask-WTF (CSRF), vanilla JS (HTML5 drag-and-drop, XMLHttpRequest for upload progress), Jinja2.

**Spec:** `docs/superpowers/specs/2026-05-10-flexlog-m6-session-ux-settings-design.md`

**Coverage floor:** ≥85% via `pyproject.toml --cov-fail-under=85` (from memory: `feedback_test_coverage.md`).

---

## File map

**New:**
- `flexlog/migrations/__init__.py` — package init.
- `flexlog/migrations/v1_to_v2.py` — `migrate_v1_to_v2(engine)` plus `migrate_to_latest(engine)`.
- `flexlog/web/upload_bp.py` — `POST /sessions/upload`, `DELETE /sessions/upload/<file_key>`.
- `flexlog/templates/settings/_app.html`, `_ratings.html`, `_ui_strings.html`, `_limits.html`, `_raw.html` — five tab partials.
- `flexlog/static/js/settings.js` — tab switching, drag-reorder, inline add/delete.
- `flexlog/static/js/session_form.js` — async upload state, link Add UI, beforeunload.
- `tests/unit/test_config_schema_v2.py`, `tests/unit/test_validate_config_dict.py`, `tests/unit/test_migrations.py`, `tests/unit/test_link_media_service.py`.
- `tests/integration/test_settings_routes.py`, `tests/integration/test_session_async_upload.py`, `tests/integration/test_session_form_e2e.py`, `tests/integration/test_detail_order.py`.

**Modified:**
- `flexlog/config_loader.py` — extract `validate_config_dict`; add `schema_version`, `sortable`; relax `scale_max` to ≤100; new bootstrap JSON.
- `flexlog/db/__init__.py` — call `migrate_to_latest(engine)` inside `attach_engine_at_runtime` after the engine is attached.
- `flexlog/db/models.py` — drop `Session.overall_score`, rename `custom_ratings_json` → `ratings_json`, drop `ck_session_overall_score`.
- `flexlog/services/sessions.py` — drop `overall_score` param, switch reads/writes to `ratings_json`, refactor `_validate_inputs` and `split_custom_ratings`.
- `flexlog/services/people.py` — `list_dashboard_rows` derives `avg_*` from `ratings_json`; sort options driven by `ratings[].sortable`.
- `flexlog/services/media.py` — add `orphan_delete_media_file(db, file_key)` helper.
- `flexlog/web/sessions_bp.py` — accept `photo_keys[]`/`audio_keys[]`/`video_keys[]`/`link_urls[]`/`unlinked_keys[]`; drop multipart-decoding helpers; drop the `overall_score` form field path.
- `flexlog/web/dashboard_bp.py` — dashboard sort options come from `[r for r in cfg.ratings if r.sortable]`.
- `flexlog/web/settings_bp.py` — full rewrite (keep `change_password`); add five POST handlers.
- `flexlog/web/__init__.py` — register `upload_bp`.
- `flexlog/web/forms.py` — drop `overall_score` field from `SessionForm`.
- `flexlog/templates/_base.html` — add `<meta name="csrf-token" content="{{ csrf_token() }}">` in `<head>`.
- `flexlog/templates/settings/index.html` — base page with tab nav; keep "Change password" section.
- `flexlog/templates/sessions/_form_body.html` — new pending-uploads UI + new links UI; remove `overall_score` input.
- `flexlog/templates/sessions/detail.html` — section reorder (Links → Ratings → Notes → Audio → Photos → Videos).
- `flexlog/templates/_partials/media_audio.html` — drop the `<a class="audio-download">` anchor.
- `flexlog/static/css/main.css` — drop `.audio-download`; add styles for `.pending-list`, `.upload-row`, `.upload-progress`, `.settings-tabs`, `.rating-row`.
- `tests/conftest.py` — bootstrap creates schema with `PRAGMA user_version = 2`; fixture ratings include a default `energy` dimension.
- `pyproject.toml` — version bump to `0.3.0`.
- `README.md` — document new `/settings`, async upload flow, migration semantics.

**Deleted:** none.

---

## Constraints (from saved memory)

- **Implementation models:** Opus and Sonnet only; never Haiku (`feedback_implementation_models.md`).
- **Test coverage:** ≥85% enforced by `pyproject.toml --cov-fail-under=85` (`feedback_test_coverage.md`).
- All new endpoints are authed + CSRF-protected.

---

---

## Task 1: Extract `validate_config_dict` from `load_config`

Pure refactor; the dict→`Config` validation path becomes a standalone public function. `load_config` shrinks to: read file → `json.loads` → `validate_config_dict`. No behavior change yet.

**Files:**
- Modify: `flexlog/config_loader.py`
- Test: `tests/unit/test_validate_config_dict.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_validate_config_dict.py`:

```python
"""validate_config_dict is the pure dict→Config validator extracted from
load_config so the settings UI can re-use it for partial-section saves."""
from __future__ import annotations

import json

from flexlog.config_loader import DEFAULT_CONFIG_JSON, validate_config_dict


def test_validate_config_dict_accepts_default_bootstrap():
    cfg, errors = validate_config_dict(json.loads(DEFAULT_CONFIG_JSON))
    assert errors == []
    assert cfg is not None
    assert cfg.app.name == "Interview Log"


def test_validate_config_dict_returns_errors_for_bad_input():
    cfg, errors = validate_config_dict({"app": "not an object"})
    assert cfg is None
    assert any("app" in e for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_validate_config_dict.py -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'validate_config_dict'`.

- [ ] **Step 3: Implement `validate_config_dict`**

In `flexlog/config_loader.py`, replace the body of `load_config` with a thin wrapper that calls a new public function. Add this above `load_config`:

```python
def validate_config_dict(raw: dict) -> tuple[Config | None, list[str]]:
    """Validate a parsed config dict. Returns (cfg, []) on success or
    (None, [error, ...]) on validation failure. Public for the settings UI
    to reuse for partial-section saves."""
    if not isinstance(raw, dict):
        return None, ["config must be a JSON object at the top level"]

    errors: list[str] = []
    app = _parse_app(raw.get("app"), errors)
    ratings = _parse_ratings(raw.get("ratings"), errors)
    ui_strings = _parse_ui_strings(raw.get("ui_strings"), errors)
    limits = _parse_limits(raw.get("limits"), errors)

    if errors:
        return None, errors
    assert app is not None and ratings is not None and limits is not None
    return Config(app=app, ratings=ratings, ui_strings=ui_strings, limits=limits), []
```

Refactor `load_config` to use it:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_validate_config_dict.py -v --no-cov`
Expected: PASS, 2 tests.

- [ ] **Step 5: Run full suite to confirm no regression**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: all existing tests pass; coverage ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/config_loader.py tests/unit/test_validate_config_dict.py
git commit -m "refactor: extract validate_config_dict from load_config

Pure refactor — the dict→Config validation path is now reachable
without going through the disk. The settings UI will use it for
partial-section saves (merge submitted tab over current config →
validate → atomic write)."
```

---

## Task 2: Add `schema_version` + `sortable` config fields; relax `scale_max` to ≤100

Spec §3 requires `schema_version: int` at the top of `config.json`, `sortable: bool` on each rating dimension (default true), and a `scale_max` upper bound of 100 instead of the current 5. Defaults stay 0–5 but the validator no longer caps it.

**Files:**
- Modify: `flexlog/config_loader.py`
- Test: `tests/unit/test_config_schema_v2.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_config_schema_v2.py`:

```python
"""Validation of the v2 config schema fields: schema_version, sortable,
and the relaxed scale_max."""
from __future__ import annotations

from flexlog.config_loader import validate_config_dict


_BASE = {
    "schema_version": 2,
    "app": {
        "name": "App", "entity_singular": "Guest", "entity_plural": "Guests",
        "session_singular": "Interview", "session_plural": "Interviews",
    },
    "ratings": [],
    "ui_strings": {},
    "limits": {
        "max_custom_rating_dimensions": 6,
        "max_audio_files_per_session": 10,
        "max_video_files_per_session": 10,
        "max_photo_files_per_session": 50,
        "max_upload_mb_per_file": 100,
    },
}


def _with_ratings(ratings):
    d = dict(_BASE)
    d["ratings"] = ratings
    return d


def test_schema_version_required_and_must_be_2():
    d = dict(_BASE)
    del d["schema_version"]
    cfg, errors = validate_config_dict(d)
    assert cfg is None and any("schema_version" in e for e in errors)

    d2 = dict(_BASE); d2["schema_version"] = 1
    cfg, errors = validate_config_dict(d2)
    assert cfg is None and any("schema_version" in e for e in errors)


def test_sortable_defaults_to_true_when_omitted():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 5, "enabled": True},
    ]))
    assert errors == []
    assert cfg.ratings[0].sortable is True


def test_sortable_explicit_false_is_preserved():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 5,
         "enabled": True, "sortable": False},
    ]))
    assert errors == []
    assert cfg.ratings[0].sortable is False


def test_scale_max_up_to_100_accepted():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 100, "enabled": True},
    ]))
    assert errors == [] and cfg.ratings[0].scale_max == 100


def test_scale_max_over_100_rejected():
    cfg, errors = validate_config_dict(_with_ratings([
        {"id": "x", "label": "X", "scale_min": 0, "scale_max": 101, "enabled": True},
    ]))
    assert cfg is None and any("scale_max" in e for e in errors)
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_config_schema_v2.py -v --no-cov`
Expected: 5 failures (schema_version not required; sortable attribute missing; scale_max>5 rejected).

- [ ] **Step 3: Update `RatingDimension` dataclass + parsers**

In `flexlog/config_loader.py`:

```python
@dataclass(frozen=True)
class RatingDimension:
    id: str
    label: str
    description: str | None
    scale_min: int
    scale_max: int
    enabled: bool
    sortable: bool = True
```

Update `_parse_ratings` — replace the scale_max check and add the sortable parse. Find the existing block:

```python
        if not isinstance(scale_max, int) or scale_max > 5 or scale_max <= scale_min:
            errors.append(f"{prefix}.scale_max must be an integer in (scale_min, 5]")
            continue
```

Replace with:

```python
        if not isinstance(scale_max, int) or scale_max > 100 or scale_max <= scale_min:
            errors.append(f"{prefix}.scale_max must be an integer in (scale_min, 100]")
            continue
```

After the `enabled` parse block, before `out.append(RatingDimension(...))`, add:

```python
        sortable = entry.get("sortable", True)
        if not isinstance(sortable, bool):
            errors.append(f"{prefix}.sortable must be a boolean")
            continue
```

And in the `RatingDimension(...)` constructor add `sortable=sortable`.

In `validate_config_dict` (added in Task 1), check `schema_version` at the top. Add right after the `isinstance(raw, dict)` guard:

```python
    sv = raw.get("schema_version")
    if sv != 2:
        return None, [f"schema_version must be 2; got {sv!r}"]
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_config_schema_v2.py -v --no-cov`
Expected: 5 PASS.

- [ ] **Step 5: Update existing tests + DEFAULT_CONFIG_JSON**

The current `DEFAULT_CONFIG_JSON` lacks `schema_version`. Existing tests that exercise validation will now fail. Update `DEFAULT_CONFIG_JSON` to include `schema_version: 2`, and update the existing fixture config in `tests/conftest.py` if it inlines a config (it uses `DEFAULT_CONFIG_JSON` directly, so this should propagate).

In `flexlog/config_loader.py`, replace the literal `DEFAULT_CONFIG_JSON` with the v2 default per spec §3:

```python
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
    "max_audio_files_per_session": 10,
    "max_video_files_per_session": 10,
    "max_photo_files_per_session": 50,
    "max_upload_mb_per_file": 3000
  }
}
"""
```

- [ ] **Step 6: Run full suite — note expected breakages**

Run: `.venv/bin/python -m pytest 2>&1 | tail -10`
Expected: many failures in existing config tests (they hardcoded `overall_quality`/`clarity`) and in session tests (they still expect the `overall_score` form input). These are addressed in Task 5. Verify the failures are only in the expected places.

- [ ] **Step 7: Commit**

```bash
git add flexlog/config_loader.py tests/unit/test_config_schema_v2.py
git commit -m "config: add schema_version + sortable, relax scale_max to <=100

schema_version=2 required at the top of config.json (v2 marker).
ratings[].sortable defaults to true; the dashboard sort dropdown
lists only sortable dimensions. scale_max ceiling lifts from 5 to
100 so users can configure 0-10 or 1-100 scales.

Default bootstrap config now ships one example dimension (energy);
the old overall_quality + clarity defaults are removed.

Existing tests that relied on the v1 defaults break here; they are
fixed by the test-suite adaptation that follows the schema rename
in subsequent tasks."
```

---

## Task 3: Migration script v1 → v2 (PRAGMA user_version)

Pure unit-tested migration function. It opens an old-shape DB, copies each session's `overall_score` into `ratings_json` under the key `"overall_score"`, drops the column, and bumps `PRAGMA user_version` from 0 (or 1) to 2. Idempotent: reruns on a v2 DB are no-ops.

**Files:**
- Create: `flexlog/migrations/__init__.py`, `flexlog/migrations/v1_to_v2.py`
- Test: `tests/unit/test_migrations.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_migrations.py`:

```python
"""v1 → v2 schema migration: drop overall_score, rename
custom_ratings_json → ratings_json, merge overall_score into
the JSON under the stable key 'overall_score'."""
from __future__ import annotations

import json

from sqlalchemy import text

from flexlog.migrations.v1_to_v2 import migrate_v1_to_v2


def _make_v1_engine(tmp_path):
    """Build an old-shape DB (no SQLCipher; plain SQLite is fine for the
    migration unit test). Schema matches what v0.2.0 wrote."""
    from sqlalchemy import create_engine
    db = tmp_path / "v1.db"
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as c:
        c.execute(text("PRAGMA user_version = 0"))
        c.execute(text("""
            CREATE TABLE session (
              id TEXT PRIMARY KEY,
              person_id TEXT NOT NULL,
              session_date TEXT NOT NULL,
              overall_score INTEGER NOT NULL,
              custom_ratings_json TEXT,
              notes TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """))
        c.execute(text("""
            INSERT INTO session VALUES
              ('s1', 'p1', '2026-01-01', 4, '{"clarity": 3}', NULL, 'now', 'now'),
              ('s2', 'p1', '2026-01-02', 5, NULL, NULL, 'now', 'now'),
              ('s3', 'p1', '2026-01-03', 2, 'not json', NULL, 'now', 'now')
        """))
    return engine


def test_migrate_v1_to_v2_merges_overall_score_into_json(tmp_path):
    engine = _make_v1_engine(tmp_path)
    migrate_v1_to_v2(engine)

    with engine.begin() as c:
        version = c.execute(text("PRAGMA user_version")).scalar()
        assert version == 2

        rows = list(c.execute(text(
            "SELECT id, ratings_json FROM session ORDER BY id"
        )))

    s1 = json.loads(rows[0][1])
    assert s1 == {"overall_score": 4, "clarity": 3}

    s2 = json.loads(rows[1][1])
    assert s2 == {"overall_score": 5}

    # Corrupted custom_ratings_json falls back to {} merged with overall_score
    s3 = json.loads(rows[2][1])
    assert s3 == {"overall_score": 2}


def test_migrate_v1_to_v2_drops_overall_score_column(tmp_path):
    engine = _make_v1_engine(tmp_path)
    migrate_v1_to_v2(engine)
    with engine.begin() as c:
        cols = [r[1] for r in c.execute(text("PRAGMA table_info(session)"))]
    assert "overall_score" not in cols
    assert "ratings_json" in cols
    assert "custom_ratings_json" not in cols


def test_migrate_v1_to_v2_is_idempotent(tmp_path):
    engine = _make_v1_engine(tmp_path)
    migrate_v1_to_v2(engine)
    migrate_v1_to_v2(engine)  # second run must be a no-op
    with engine.begin() as c:
        version = c.execute(text("PRAGMA user_version")).scalar()
        rows = list(c.execute(text("SELECT ratings_json FROM session ORDER BY id")))
    assert version == 2
    assert json.loads(rows[0][0]) == {"overall_score": 4, "clarity": 3}
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_migrations.py -v --no-cov`
Expected: ImportError on `flexlog.migrations.v1_to_v2`.

- [ ] **Step 3: Implement the migration**

Create `flexlog/migrations/__init__.py`:

```python
"""flexlog schema migrations. Triggered from db.attach_engine_at_runtime;
idempotent."""
```

Create `flexlog/migrations/v1_to_v2.py`:

```python
"""v1 → v2: drop Session.overall_score, rename custom_ratings_json →
ratings_json, merge overall_score into the JSON under the stable id
'overall_score'.

Triggered from `flexlog.db.attach_engine_at_runtime`. Idempotent on a
DB that already reports `PRAGMA user_version >= 2`.
"""
from __future__ import annotations

import json

from sqlalchemy import Engine, text

TARGET_VERSION = 2


def _table_has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return any(r[1] == column for r in rows)


def _parse_or_empty(raw):
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def migrate_v1_to_v2(engine: Engine) -> None:
    """Apply the v1 → v2 migration. No-op on a v2 DB."""
    with engine.begin() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar() or 0
        if version >= TARGET_VERSION:
            return

        # Verify the column actually exists before attempting the move. Belt
        # and braces — covers the case of a half-migrated DB from a prior
        # crash where user_version stayed at 0 but the column is already
        # gone.
        has_overall_score = _table_has_column(conn, "session", "overall_score")
        has_old_json = _table_has_column(conn, "session", "custom_ratings_json")
        has_new_json = _table_has_column(conn, "session", "ratings_json")

        if has_new_json and not has_overall_score and not has_old_json:
            # Schema is already at v2 shape; just bump the version pragma.
            conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION}"))
            return

        # Add the new column if not present yet.
        if not has_new_json:
            conn.execute(text("ALTER TABLE session ADD COLUMN ratings_json TEXT"))

        # Copy data: merge overall_score into the (possibly NULL) JSON dict.
        rows = list(conn.execute(text(
            "SELECT id, overall_score, custom_ratings_json FROM session"
        )))
        for sid, overall, raw in rows:
            merged = _parse_or_empty(raw)
            if overall is not None:
                merged["overall_score"] = int(overall)
            conn.execute(
                text("UPDATE session SET ratings_json = :j WHERE id = :i"),
                {"j": json.dumps(dict(sorted(merged.items()))), "i": sid},
            )

        # Drop the obsolete columns. SQLite 3.35+ supports ALTER TABLE DROP
        # COLUMN; SQLCipher 4.x ships with SQLite >= 3.35.
        if has_overall_score:
            conn.execute(text("ALTER TABLE session DROP COLUMN overall_score"))
        if has_old_json:
            conn.execute(text("ALTER TABLE session DROP COLUMN custom_ratings_json"))

        conn.execute(text(f"PRAGMA user_version = {TARGET_VERSION}"))


def migrate_to_latest(engine: Engine) -> None:
    """Run all pending migrations in order. Call this from anywhere that
    attaches an engine (login, setup, test fixtures)."""
    migrate_v1_to_v2(engine)
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_migrations.py -v --no-cov`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add flexlog/migrations/__init__.py flexlog/migrations/v1_to_v2.py tests/unit/test_migrations.py
git commit -m "migrations: v1 to v2 schema migration

Drop Session.overall_score, rename custom_ratings_json to
ratings_json, merge the dropped column into the JSON under the
stable id 'overall_score'. Idempotent via PRAGMA user_version;
guards against partial/aborted runs by inspecting actual table
columns before acting.

Not wired into startup yet (next task); this commit ships only
the migration function + its unit tests."
```

---

## Task 4: Wire `migrate_to_latest` into `attach_engine_at_runtime`

Every engine attach — login (`landing_bp.submit`), setup (`setup_bp.set_password`), and test fixtures — must trigger migration before the engine is used. Centralizing this inside `attach_engine_at_runtime` avoids forgetting it at one of the call sites.

**Files:**
- Modify: `flexlog/db/__init__.py`
- Test: `tests/integration/test_migration_on_attach.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_migration_on_attach.py`:

```python
"""Verify that attach_engine_at_runtime triggers migrate_to_latest.

The test fixture's `app` already calls attach_engine_at_runtime, so by
the time we touch the engine, user_version should already be 2."""
from __future__ import annotations

from sqlalchemy import text


def test_attach_engine_at_runtime_runs_migrations(app):
    engine = app.config["FLEXLOG_DB_ENGINE"]
    with engine.begin() as c:
        version = c.execute(text("PRAGMA user_version")).scalar()
    assert version == 2
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_migration_on_attach.py -v --no-cov`
Expected: FAIL — `user_version` is 0 because nothing has bumped it.

- [ ] **Step 3: Wire migration into the attach helper**

In `flexlog/db/__init__.py`, modify `attach_engine_at_runtime` to call `migrate_to_latest` after attaching:

```python
def attach_engine_at_runtime(app: Flask, engine: Engine,
                              session_factory: sessionmaker[Session]) -> None:
    """Swap a fresh engine + factory into the app config AFTER login.

    Dispose any existing engine first (closes its pooled connections).
    Assumes `register_db_teardown(app)` was already called at app-factory
    time so per-request sessions get closed by Flask's teardown hook.
    After attaching, runs any pending schema migrations on the new engine
    so post-login code never observes a stale schema."""
    old = app.config.get(_ENGINE_KEY)
    if old is not None and old is not engine:
        try:
            old.dispose()
        except Exception:
            pass
    app.config[_ENGINE_KEY] = engine
    app.config[_FACTORY_KEY] = session_factory

    # Local import — flexlog.migrations imports SQLAlchemy at module top,
    # which is fine, but the migration module imports `text` which is already
    # imported here. Keeping the import local makes the dependency direction
    # one-way (db doesn't depend on migrations at import time).
    from flexlog.migrations.v1_to_v2 import migrate_to_latest
    migrate_to_latest(engine)
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/integration/test_migration_on_attach.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Confirm fixture-built DBs still work**

The `tests/conftest.py:_bootstrap_encrypted_dir` helper uses `Base.metadata.create_all(engine)` against the **future v2 shape** (after the model change in Task 5 lands). For this commit, the shape is still v1; `create_all` builds v1 tables, then the migration runs on attach and bumps the schema to v2 in-place. This is exactly the migration path real users will take.

Run: `.venv/bin/python -m pytest tests/integration/test_migration_on_attach.py tests/unit/test_migrations.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add flexlog/db/__init__.py tests/integration/test_migration_on_attach.py
git commit -m "db: run migrate_to_latest on every engine attach

Centralizes migration triggering in attach_engine_at_runtime so
the four call sites (landing.submit, setup.set_password, and two
test fixtures) get it automatically. After attach, the engine
always reports PRAGMA user_version = current latest."
```

---

## Task 5: DB schema + service layer — drop `overall_score`, switch to `ratings_json`

The big breaking change. Drop `Session.overall_score`, rename `custom_ratings_json` → `ratings_json`, drop the `ck_session_overall_score` CheckConstraint. Adapt the service layer (`create_session`/`update_session`/`split_custom_ratings` and friends) to take a unified `ratings: dict[str, int]` instead of `overall_score` + `custom_ratings`. Adapt `sessions_bp` route handlers to parse the unified form. Update the test fixtures/conftest. Update the `SessionForm` WTForm to drop `overall_score`.

This task touches a lot and breaks tests in-flight; the verification step is to keep the full suite green.

**Files:**
- Modify: `flexlog/db/models.py`, `flexlog/services/sessions.py`, `flexlog/web/sessions_bp.py`, `flexlog/web/forms.py`, `tests/conftest.py`, plus every test that POSTs `overall_score=<n>` (find them via grep)
- Test: existing suite must stay green

- [ ] **Step 1: Update the model**

In `flexlog/db/models.py`, in the `Session` class:

Remove these two lines:

```python
    overall_score: Mapped[int] = mapped_column(nullable=False)
    custom_ratings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Replace with:

```python
    ratings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Update `__table_args__` to drop the CheckConstraint:

```python
    __table_args__ = (
        Index("ix_session_person_date", "person_id", "session_date"),
    )
```

- [ ] **Step 2: Update `services/sessions.py`**

Replace the module verbatim:

```python
"""Session CRUD + rating split.

Sessions belong to a person and carry optional notes, a unified
ratings dict (stored as JSON keyed by rating-dimension id, validated
against config at write time), and zero or more SessionLinks.

split_ratings() is the read-side helper: given the stored JSON and
the currently enabled rating IDs from config, it returns
(current_pairs, archived_pairs) for the template to render.
"""

from __future__ import annotations

import json
import re
import uuid

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from flexlog.db.models import Person, Session as SessionRow, SessionLink

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def enabled_rating_dimensions():
    """Return the list of enabled rating dimensions from app config."""
    cfg = current_app.config["FLEXLOG"]
    return [r for r in cfg.ratings if r.enabled]


class SessionNotFoundError(LookupError):
    """Raised by update/delete when the target session id does not exist."""


def _validate_inputs(person: Person | None, session_date: str) -> None:
    if person is None:
        raise ValueError("person not found for the given person_id")
    if not isinstance(session_date, str) or not _DATE_RE.match(session_date):
        raise ValueError(f"session_date must be ISO YYYY-MM-DD, got {session_date!r}")


def _serialize_ratings(ratings: dict[str, int]) -> str:
    """Deterministic JSON-string serialization of the ratings dict."""
    return json.dumps(dict(sorted(ratings.items())))


def _replace_links(
    db: Session,
    session_row: SessionRow,
    urls: list[str],
    preserve_thumbnails: list[str | None] | None = None,
) -> None:
    """Drop existing links and recreate from the URL list."""
    session_row.links = []
    new_link_index = 0
    for i, raw in enumerate(urls):
        url = (raw or "").strip()
        if not url:
            continue
        thumb_id: str | None = None
        if preserve_thumbnails is not None and new_link_index < len(preserve_thumbnails):
            thumb_id = preserve_thumbnails[new_link_index]
        session_row.links.append(
            SessionLink(
                id=str(uuid.uuid4()),
                session_id=session_row.id,
                url=url,
                label=None,
                sort_order=i,
                thumbnail_media_id=thumb_id,
            )
        )
        new_link_index += 1


def create_session(
    db: Session,
    person_id: str,
    session_date: str,
    ratings: dict[str, int],
    notes: str | None,
    link_urls: list[str],
) -> SessionRow:
    """Create a Session row + its links. Caller commits.

    Media linking is handled separately via link_media_to_session — this
    function no longer accepts FileStorage uploads. Routes call the upload
    endpoint to encrypt+store, then call this with the file_keys."""
    person = db.get(Person, person_id)
    _validate_inputs(person, session_date)

    session_row = SessionRow(
        id=str(uuid.uuid4()),
        person_id=person_id,
        session_date=session_date,
        ratings_json=_serialize_ratings(ratings),
        notes=(notes or None) if (notes is None or notes.strip() == "") else notes,
    )
    db.add(session_row)
    db.flush()
    _replace_links(db, session_row, link_urls)
    return session_row


def get_session(db: Session, session_id: str) -> SessionRow | None:
    stmt = (
        select(SessionRow)
        .where(SessionRow.id == session_id)
        .options(selectinload(SessionRow.links), selectinload(SessionRow.person))
    )
    return db.execute(stmt).scalar_one_or_none()


def list_sessions_for_person(db: Session, person_id: str) -> list[SessionRow]:
    """All sessions for `person_id`, newest first."""
    stmt = (
        select(SessionRow)
        .where(SessionRow.person_id == person_id)
        .order_by(SessionRow.session_date.desc())
        .options(selectinload(SessionRow.links))
    )
    return list(db.execute(stmt).scalars())


def update_session(
    db: Session,
    session_id: str,
    session_date: str,
    ratings: dict[str, int],
    notes: str | None,
    link_urls: list[str],
) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    _validate_inputs(session_row.person, session_date)
    session_row.session_date = session_date
    session_row.ratings_json = _serialize_ratings(ratings)
    session_row.notes = notes if (notes and notes.strip()) else None

    existing_thumbs: list[str | None] = [li.thumbnail_media_id for li in session_row.links]
    _replace_links(db, session_row, link_urls, preserve_thumbnails=existing_thumbs)
    return session_row


def delete_session(db: Session, session_id: str) -> None:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    db.delete(session_row)


def split_ratings(
    stored_json: str | None,
    enabled_ids: list[str],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Split stored ratings into (current, archived).

    `current` follows the order of `enabled_ids`; only IDs whose value is
    actually stored appear. `archived` is everything stored but absent
    from `enabled_ids`, in stored insertion order.
    """
    if not stored_json:
        return [], []
    try:
        stored = json.loads(stored_json)
    except (ValueError, TypeError):
        return [], []
    if not isinstance(stored, dict):
        return [], []
    enabled_set = set(enabled_ids)
    current: list[tuple[str, int]] = []
    for rid in enabled_ids:
        if rid in stored and isinstance(stored[rid], int):
            current.append((rid, stored[rid]))
    archived: list[tuple[str, int]] = []
    for rid, val in stored.items():
        if rid not in enabled_set and isinstance(val, int):
            archived.append((rid, val))
    return current, archived


# Backwards-compat alias used by older test files until they're updated.
split_custom_ratings = split_ratings
```

- [ ] **Step 3: Update `web/forms.py`**

Drop the `overall_score` field from `SessionForm`. The form becomes:

```python
class SessionForm(FlaskForm):
    session_date = StringField(
        "session_date",
        validators=[
            DataRequired(message="session_date is required"),
            Regexp(_DATE_RE, message="session_date must be ISO YYYY-MM-DD"),
        ],
    )
    notes = TextAreaField(
        "notes",
        validators=[Optional(), Length(max=NOTES_MAX)],
    )
```

Remove the `IntegerField` and `NumberRange` imports if they become unused.

- [ ] **Step 4: Update `web/sessions_bp.py` — accept unified ratings + URL-only links**

Replace `_parse_custom_ratings_from_request` and `_parse_links_from_request`:

```python
def _parse_ratings_from_request() -> dict[str, int]:
    """Pull rating_<id> form fields. Values outside the dim's scale are dropped."""
    out: dict[str, int] = {}
    for dim in enabled_rating_dimensions():
        raw = (request.form.get(f"rating_{dim.id}") or "").strip()
        if not raw:
            continue
        try:
            val = int(raw)
        except ValueError:
            continue
        if dim.scale_min <= val <= dim.scale_max:
            out[dim.id] = val
    return out


def _parse_link_urls_from_request() -> list[str]:
    """Read link_urls[] in submitted order, drop blanks."""
    return [u for u in request.form.getlist("link_urls") if (u or "").strip()]
```

Delete `_gather_uploads` and `_gather_link_thumbnails`.

Update the `new` handler (no `overall_score`):

```python
@sessions_bp.get("/people/<person_id>/sessions/new")
def new(person_id: str):
    person = _person_or_404(person_id)
    form = SessionForm()
    return render_template(
        "sessions/new.html",
        form=form,
        person=person,
        rating_dimensions=enabled_rating_dimensions(),
        existing_ratings={},
        existing_link_urls=[],
        existing_media={"photo": [], "audio": [], "video": []},
    )
```

Update the `create` handler:

```python
@sessions_bp.post("/people/<person_id>/sessions")
def create(person_id: str):
    person = _person_or_404(person_id)
    form = SessionForm()
    rating_dimensions = enabled_rating_dimensions()
    if not form.validate_on_submit():
        return render_template(
            "sessions/new.html",
            form=form,
            person=person,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_ratings_from_request(),
            existing_link_urls=_parse_link_urls_from_request(),
            existing_media={"photo": [], "audio": [], "video": []},
        ), 400
    db = get_db()
    session_row = create_session(
        db,
        person_id=person.id,
        session_date=form.session_date.data,
        ratings=_parse_ratings_from_request(),
        notes=(form.notes.data or None),
        link_urls=_parse_link_urls_from_request(),
    )
    # Media linking — handled in Task 7's service + this route in Task 10.
    db.commit()
    return redirect(url_for("sessions.detail", session_id=session_row.id))
```

Update the `detail` and `edit` handlers to use `split_ratings` and `ratings_json`:

```python
@sessions_bp.get("/sessions/<session_id>")
def detail(session_id: str):
    s = _session_or_404(session_id)
    enabled_ids = [d.id for d in enabled_rating_dimensions()]
    current, archived = split_ratings(s.ratings_json, enabled_ids)
    label_map = {d.id: d.label for d in enabled_rating_dimensions()}
    current_with_labels = [(rid, label_map[rid], val) for rid, val in current]
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
        current_ratings=current_with_labels,
        archived_ratings=archived,
        photos=photos, audios=audios, videos=videos,
        link_thumbnails=link_thumbnails,
    )
```

Adjust the import line near the top: replace `split_custom_ratings` with `split_ratings`.

Update the `edit` handler:

```python
@sessions_bp.get("/sessions/<session_id>/edit")
def edit(session_id: str):
    s = _session_or_404(session_id)
    form = SessionForm(data={"session_date": s.session_date, "notes": s.notes or ""})
    enabled_ids = [d.id for d in enabled_rating_dimensions()]
    current_pairs, _ = split_ratings(s.ratings_json, enabled_ids)
    existing_ratings = dict(current_pairs)
    existing_link_urls = [li.url for li in s.links]
    grouped: dict[str, list] = {"photo": [], "audio": [], "video": []}
    for j in s.media_joins:
        grouped[j.media_file.media_type].append(j.media_file)
    return render_template(
        "sessions/edit.html",
        form=form,
        person=s.person,
        session=s,
        rating_dimensions=enabled_rating_dimensions(),
        existing_ratings=existing_ratings,
        existing_link_urls=existing_link_urls,
        existing_media=grouped,
    )
```

Update `update`:

```python
@sessions_bp.post("/sessions/<session_id>")
def update(session_id: str):
    s = _session_or_404(session_id)
    form = SessionForm()
    rating_dimensions = enabled_rating_dimensions()
    if not form.validate_on_submit():
        grouped: dict[str, list] = {"photo": [], "audio": [], "video": []}
        for j in s.media_joins:
            grouped[j.media_file.media_type].append(j.media_file)
        return render_template(
            "sessions/edit.html",
            form=form,
            person=s.person,
            session=s,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_ratings_from_request(),
            existing_link_urls=_parse_link_urls_from_request(),
            existing_media=grouped,
        ), 400
    db = get_db()
    try:
        update_session(
            db, session_id,
            session_date=form.session_date.data,
            ratings=_parse_ratings_from_request(),
            notes=(form.notes.data or None),
            link_urls=_parse_link_urls_from_request(),
        )
    except SessionNotFoundError:
        abort(404)
    db.commit()
    return redirect(url_for("sessions.detail", session_id=session_id))
```

Remove unused imports (`MediaUploadError`, `flash` if unused, etc.) until the file lints clean.

- [ ] **Step 5: Update existing test files that POST `overall_score=<n>`**

Find them:

```bash
grep -rln "overall_score" tests/
```

For each test file in that list, replace the form field `overall_score` with `rating_overall_score` (the v2 default config doesn't ship that dimension, but the migration creates that key when migrating real data; tests that need the field can use `rating_energy` since the new bootstrap config has `energy`). For sessions created via `create_session` service calls, swap the kwarg:

- `overall_score=4, custom_ratings={"clarity": 3}` → `ratings={"energy": 4, "clarity": 3}`
- Reads of `session.overall_score` → `json.loads(session.ratings_json)["energy"]`
- `session.custom_ratings_json` → `session.ratings_json`

For form POSTs in integration tests: `overall_score=4` form field → `rating_energy=4`.

Update `tests/conftest.py:_bootstrap_encrypted_dir` if it inlines any specific schema state (it uses `Base.metadata.create_all`, which produces the new shape — fine). After `Base.metadata.create_all(engine)`, set the `user_version` so the migration is a no-op on the fresh fixture DB:

In the function body, after the `Base.metadata.create_all(engine)` line, add:

```python
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("PRAGMA user_version = 2"))
```

- [ ] **Step 6: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -20`

Expected: All tests pass after the test-file edits in Step 5. If any fail with `AttributeError: ... has no attribute 'overall_score'` or `KeyError: 'overall_score'`, that file still references the old shape — fix it.

Coverage may dip slightly because dead branches in `services/sessions.py` are gone; that's expected. Coverage must stay ≥85%.

- [ ] **Step 7: Commit**

```bash
git add flexlog/db/models.py flexlog/services/sessions.py flexlog/web/forms.py flexlog/web/sessions_bp.py tests/
git commit -m "schema: drop overall_score, rename to ratings_json

Session.overall_score is gone; all ratings live in ratings_json as
{id: int} keyed by the rating-dimension id from config. The CHECK
constraint on the old column is removed; per-dimension scale checks
now happen at write time in the route handler against config bounds.

Service signature simplifies: create_session/update_session take a
ratings dict instead of overall_score + custom_ratings. Routes parse
rating_<id> form inputs uniformly.

WTForm drops the overall_score IntegerField; link inputs become
link_urls[] (no label field, no thumbnail upload here — thumbnails
keep working through the existing link_thumbnail_media_id column).

Tests adapted. Coverage stays above the 85% floor."
```

---

## Task 6: Dashboard sort options derive from `ratings[].sortable`

`services/people.py:list_dashboard_rows` previously aggregated `Session.overall_score`. With that gone, the dashboard's `avg_score` sort must be replaced — and we want only sortable rating dimensions to appear in the dropdown.

**Files:**
- Modify: `flexlog/services/people.py`, `flexlog/web/dashboard_bp.py`, `flexlog/templates/dashboard.html`
- Test: `tests/integration/test_dashboard_sort_v2.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_dashboard_sort_v2.py`:

```python
"""Dashboard sort options are derived from config: only ratings whose
sortable=True appear in the dropdown. Sorting by a sortable dim uses
the Python-side average of that dimension across sessions."""
from __future__ import annotations

import json


def _make_person_with_ratings(db_session, alias, ratings_per_session):
    """Helper: create a person + N sessions with the given ratings dicts."""
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session
    p = create_person(db_session, alias=alias, tag_input="")
    db_session.commit()
    for i, r in enumerate(ratings_per_session):
        create_session(
            db_session, person_id=p.id,
            session_date=f"2026-01-{i+1:02d}",
            ratings=r, notes=None, link_urls=[],
        )
    db_session.commit()
    return p


def test_dashboard_dropdown_lists_only_sortable_dimensions(authed_client, app):
    # Default bootstrap config has one dimension (energy, sortable=True).
    resp = authed_client.get("/")
    body = resp.get_data(as_text=True)
    assert "custom:energy" in body  # rendered as an <option value="custom:energy">


def test_dashboard_sort_by_custom_dim(authed_client, db_session):
    _make_person_with_ratings(db_session, "Alice", [{"energy": 5}, {"energy": 4}])
    _make_person_with_ratings(db_session, "Bob",   [{"energy": 2}])
    _make_person_with_ratings(db_session, "Carol", [])

    resp = authed_client.get("/?sort=custom:energy")
    body = resp.get_data(as_text=True)
    # Alice (avg 4.5) before Bob (avg 2.0) before Carol (no rating, NULLs last)
    a, b, c = body.index("Alice"), body.index("Bob"), body.index("Carol")
    assert a < b < c
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_dashboard_sort_v2.py -v --no-cov`
Expected: FAIL — `custom:energy` isn't in the dropdown yet (the dashboard template still references the old sort options) and `_custom_dim_averages` still reads `custom_ratings_json`.

- [ ] **Step 3: Update `services/people.py`**

Find `_VALID_SCALAR_SORTS` and remove `avg_score`:

```python
_VALID_SCALAR_SORTS = ("alias", "last_date", "session_count")
```

Update the base `select(...)` block in `list_dashboard_rows` — drop the `avg(overall_score)` column since `overall_score` no longer exists. Remove the `avg_overall_score` assignments and the `DashboardRow.avg_overall_score` field if present (keep the dataclass shape minimal — adjust the dataclass declaration too).

Update `_sort_rows` — remove the `if sort == "avg_score"` branch entirely. Keep `custom:<id>` since it's now the canonical "rating average" sort.

Update `_custom_dim_averages` to read `ratings_json` instead of `custom_ratings_json`:

```python
def _custom_dim_averages(session: Session, dim_id: str) -> dict[str, float]:
    """Return {person_id: avg_for_dim} across all sessions. Pure Python."""
    import json
    rows = session.execute(
        select(SessionRow.person_id, SessionRow.ratings_json)
    ).all()
    sums: dict[str, list[float]] = {}
    for person_id, raw in rows:
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict) or dim_id not in d:
            continue
        v = d[dim_id]
        if not isinstance(v, int):
            continue
        sums.setdefault(person_id, []).append(float(v))
    return {pid: sum(vs) / len(vs) for pid, vs in sums.items() if vs}
```

- [ ] **Step 4: Update `web/dashboard_bp.py`**

Filter `enabled_rating_dimensions` for sortable in the context:

```python
@dashboard_bp.get("/dashboard")
def home():
    query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "alias").strip() or "alias"
    rows = list_dashboard_rows(get_db(), query, sort)
    cfg = current_app.config["FLEXLOG"]
    sortable_dimensions = [r for r in cfg.ratings if r.enabled and r.sortable]
    return render_template(
        "dashboard.html",
        rows=rows,
        query=query,
        sort=sort,
        sortable_dimensions=sortable_dimensions,
    )
```

Add the import: `from flask import current_app` at the top. Drop the `enabled_rating_dimensions` import if it's no longer used in this file.

- [ ] **Step 5: Update `templates/dashboard.html`**

Find the sort `<select>`. Replace any branch that iterates `rating_dimensions` with `sortable_dimensions`, and drop the `avg_score` `<option>` if present. The dropdown ends up like:

```html
<select name="sort">
  <option value="alias" {% if sort == 'alias' %}selected{% endif %}>Alphabetical</option>
  <option value="last_date" {% if sort == 'last_date' %}selected{% endif %}>Last session</option>
  <option value="session_count" {% if sort == 'session_count' %}selected{% endif %}>Session count</option>
  {% for dim in sortable_dimensions %}
    <option value="custom:{{ dim.id }}" {% if sort == 'custom:' + dim.id %}selected{% endif %}>{{ dim.label }} (avg)</option>
  {% endfor %}
</select>
```

Also remove the column showing `row.avg_overall_score` if it's rendered (it's been dropped from `DashboardRow`).

- [ ] **Step 6: Run new + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_dashboard_sort_v2.py -v --no-cov`
Expected: 2 PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -5`
Expected: full suite green, ≥85% coverage.

- [ ] **Step 7: Commit**

```bash
git add flexlog/services/people.py flexlog/web/dashboard_bp.py flexlog/templates/dashboard.html tests/integration/test_dashboard_sort_v2.py
git commit -m "dashboard: sort options derive from ratings[].sortable

Drops the dead avg_score sort (its source column is gone). Adds a
sortable bool gate so the dropdown only lists dimensions the user
flagged. Custom-dimension averages now read from ratings_json
keyed by dim id, falling back gracefully when a session lacks
the dimension."
```

---

## Task 7: New media-linking service functions

`link_media_to_session(db, session_id, file_keys_by_kind)` creates `SessionMedia` rows. `unlink_media_from_session(db, session_id, file_keys)` removes them. `orphan_delete_media_file(db, file_key)` is a best-effort delete used by the new DELETE endpoint.

**Files:**
- Modify: `flexlog/services/sessions.py`, `flexlog/services/media.py`
- Test: `tests/unit/test_link_media_service.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_link_media_service.py`:

```python
"""link_media_to_session / unlink_media_from_session create and remove
SessionMedia join rows. orphan_delete_media_file removes a MediaFile +
its on-disk encrypted blob only if nothing references it."""
from __future__ import annotations


def _create_media_file(db, kind, sha):
    import uuid
    from flexlog.db.models import MediaFile
    mf = MediaFile(
        id=str(uuid.uuid4()), sha256=sha, file_key=f"k/{sha}",
        media_type=kind, original_filename="f.bin", mime_type="image/jpeg",
        file_size_bytes=10,
    )
    db.add(mf)
    db.flush()
    return mf


def _create_session(db, person_id):
    from flexlog.services.sessions import create_session
    return create_session(
        db, person_id=person_id, session_date="2026-01-01",
        ratings={}, notes=None, link_urls=[],
    )


def test_link_media_to_session_creates_join_rows(db_session, person):
    from flexlog.services.sessions import link_media_to_session
    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "a" * 64)
    p2 = _create_media_file(db_session, "photo", "b" * 64)
    aud = _create_media_file(db_session, "audio", "c" * 64)

    link_media_to_session(db_session, s.id, {
        "photo": [p1.file_key, p2.file_key],
        "audio": [aud.file_key],
        "video": [],
    })
    db_session.commit()

    assert len(s.media_joins) == 3
    kinds = sorted(j.media_file.media_type for j in s.media_joins)
    assert kinds == ["audio", "photo", "photo"]


def test_link_ignores_unknown_file_keys(db_session, person):
    from flexlog.services.sessions import link_media_to_session
    s = _create_session(db_session, person.id)
    link_media_to_session(db_session, s.id, {
        "photo": ["k/does-not-exist"], "audio": [], "video": [],
    })
    db_session.commit()
    assert s.media_joins == []


def test_unlink_media_removes_join_rows(db_session, person):
    from flexlog.services.sessions import link_media_to_session, unlink_media_from_session
    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "d" * 64)
    p2 = _create_media_file(db_session, "photo", "e" * 64)
    link_media_to_session(db_session, s.id, {"photo": [p1.file_key, p2.file_key],
                                              "audio": [], "video": []})
    db_session.commit()

    unlink_media_from_session(db_session, s.id, [p1.file_key])
    db_session.commit()

    remaining = [j.media_file.file_key for j in s.media_joins]
    assert remaining == [p2.file_key]


def test_orphan_delete_skips_referenced_files(db_session, person):
    from flexlog.services.media import orphan_delete_media_file
    from flexlog.services.sessions import link_media_to_session
    s = _create_session(db_session, person.id)
    p1 = _create_media_file(db_session, "photo", "f" * 64)
    link_media_to_session(db_session, s.id, {"photo": [p1.file_key],
                                              "audio": [], "video": []})
    db_session.commit()

    deleted = orphan_delete_media_file(db_session, p1.file_key)
    assert deleted is False

    from flexlog.db.models import MediaFile
    from sqlalchemy import select
    still_there = db_session.execute(
        select(MediaFile).where(MediaFile.file_key == p1.file_key)
    ).scalar_one_or_none()
    assert still_there is not None


def test_orphan_delete_removes_unreferenced_files(db_session, person, tmp_path, monkeypatch):
    from flexlog.services.media import orphan_delete_media_file
    mf = _create_media_file(db_session, "photo", "9" * 64)
    db_session.commit()

    deleted = orphan_delete_media_file(db_session, mf.file_key)
    assert deleted is True

    from flexlog.db.models import MediaFile
    from sqlalchemy import select
    assert db_session.execute(
        select(MediaFile).where(MediaFile.file_key == mf.file_key)
    ).scalar_one_or_none() is None
```

This test uses a `person` fixture — add it to `tests/conftest.py` if it doesn't exist yet:

```python
@pytest.fixture
def person(db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Test", tag_input="")
    db_session.commit()
    return p
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/unit/test_link_media_service.py -v --no-cov`
Expected: ImportError on the new helpers.

- [ ] **Step 3: Implement the helpers**

In `flexlog/services/sessions.py`, append:

```python
def link_media_to_session(
    db: Session, session_id: str, file_keys_by_kind: dict[str, list[str]]
) -> int:
    """Create SessionMedia join rows for each file_key. Unknown keys are
    silently skipped (defensive against stale form state).

    Returns the number of joins created. Caller commits."""
    from flexlog.db.models import MediaFile, SessionMedia
    from sqlalchemy import select

    existing_max_stmt = select(SessionMedia.sort_order).where(
        SessionMedia.session_id == session_id
    )
    sort_order = max(
        (row[0] for row in db.execute(existing_max_stmt)), default=-1
    ) + 1

    created = 0
    for kind in ("photo", "audio", "video"):
        for key in file_keys_by_kind.get(kind, []):
            mf = db.execute(
                select(MediaFile).where(MediaFile.file_key == key)
            ).scalar_one_or_none()
            if mf is None or mf.media_type != kind:
                continue
            db.add(SessionMedia(
                id=str(uuid.uuid4()),
                session_id=session_id,
                media_file_id=mf.id,
                sort_order=sort_order,
            ))
            sort_order += 1
            created += 1
    db.flush()
    return created


def unlink_media_from_session(
    db: Session, session_id: str, file_keys: list[str]
) -> int:
    """Remove SessionMedia rows by (session_id, file_key). Returns removed count."""
    from flexlog.db.models import MediaFile, SessionMedia
    from sqlalchemy import select, and_

    if not file_keys:
        return 0
    stmt = (
        select(SessionMedia)
        .join(MediaFile, MediaFile.id == SessionMedia.media_file_id)
        .where(and_(
            SessionMedia.session_id == session_id,
            MediaFile.file_key.in_(file_keys),
        ))
    )
    removed = 0
    for sm in db.execute(stmt).scalars():
        db.delete(sm)
        removed += 1
    return removed
```

In `flexlog/services/media.py`, append:

```python
def orphan_delete_media_file(db: Session, file_key: str) -> bool:
    """Best-effort orphan delete. If the MediaFile is referenced by any
    SessionMedia or Person.avatar_media_id, returns False without doing
    anything. Otherwise, deletes the encrypted file from disk + the row.

    Returns True iff the file was deleted."""
    from sqlalchemy import select
    from flexlog import paths
    from flexlog.db.models import MediaFile, Person, SessionMedia

    mf = db.execute(
        select(MediaFile).where(MediaFile.file_key == file_key)
    ).scalar_one_or_none()
    if mf is None:
        return False

    referenced_by_session = db.execute(
        select(SessionMedia.id).where(SessionMedia.media_file_id == mf.id).limit(1)
    ).scalar_one_or_none()
    referenced_as_avatar = db.execute(
        select(Person.id).where(Person.avatar_media_id == mf.id).limit(1)
    ).scalar_one_or_none()
    if referenced_by_session is not None or referenced_as_avatar is not None:
        return False

    target = paths.resolve_file_key(mf.file_key)
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(mf)
    db.flush()
    return True
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/unit/test_link_media_service.py -v --no-cov`
Expected: 5 PASS.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: all pass, coverage ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/services/sessions.py flexlog/services/media.py tests/unit/test_link_media_service.py tests/conftest.py
git commit -m "services: link/unlink media + orphan-delete helpers

link_media_to_session creates SessionMedia rows for a dict of
file_keys_by_kind (photo/audio/video), skipping unknown keys
defensively so stale form state can't crash a save.

unlink_media_from_session removes joins by file_key.

orphan_delete_media_file checks for any SessionMedia or Person
avatar reference; deletes the encrypted file + row only when
truly orphaned, mirroring the existing /library hard-delete."
```

---

## Task 8: Upload blueprint — `POST /sessions/upload` + `DELETE /sessions/upload/<file_key>`

The two AJAX endpoints. POST takes a single file + `kind` form field, returns JSON. DELETE is best-effort orphan delete (always 204). Both are authed + CSRF-protected via Flask-WTF's `X-CSRFToken` header support.

**Files:**
- Create: `flexlog/web/upload_bp.py`
- Modify: `flexlog/web/__init__.py`
- Test: `tests/integration/test_session_async_upload.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_session_async_upload.py`:

```python
"""POST /sessions/upload + DELETE /sessions/upload/<file_key>."""
from __future__ import annotations

import io

# A 1x1 JPEG (real JPEG bytes so magic-byte check passes).
JPEG_1x1 = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c14"
    "0d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27"
    "393d38323c2e333432ffdb0043010909090c0b0c180d0d1832211c213232323232323232323232"
    "32323232323232323232323232323232323232323232323232323232323232323232323232323232"
    "32ffc00011080001000103012200021101031101ffc4001f0000010501010101010100000000000000"
    "000102030405060708090a0bffc400b5100002010303020403050504040000017d010203000411051"
    "20613410761711322328114914223a153623e22458152732a2c2d2e2f23308293f1f25210ffc4001f"
    "0100030101010101010101010000000000000102030405060708090a0bffc400b5110002010204040"
    "30407050404000102770001020311043121052141061371229132061581914423a1b1c11425d1f02430"
    "626282939344d1f0f1ffda000c03010002110311003f00f7e8a28affd9"
)


def test_upload_endpoint_returns_file_key(csrf_authed_client):
    resp = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo", "file": (io.BytesIO(JPEG_1x1), "test.jpg", "image/jpeg")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": _csrf_token_from(csrf_authed_client)},
    )
    assert resp.status_code == 200
    j = resp.get_json()
    assert "file_key" in j
    assert j["media_type"] == "photo"
    assert j["mime"] == "image/jpeg"


def test_upload_endpoint_rejects_bad_mime(csrf_authed_client):
    resp = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo",
              "file": (io.BytesIO(b"hello"), "test.txt", "text/plain")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": _csrf_token_from(csrf_authed_client)},
    )
    assert resp.status_code == 415
    assert "error" in resp.get_json()


def test_upload_endpoint_rejects_without_csrf(csrf_authed_client):
    resp = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo",
              "file": (io.BytesIO(JPEG_1x1), "test.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code in (400, 403)  # CSRF rejection


def test_delete_endpoint_deletes_orphan(csrf_authed_client):
    token = _csrf_token_from(csrf_authed_client)
    up = csrf_authed_client.post(
        "/sessions/upload",
        data={"kind": "photo", "file": (io.BytesIO(JPEG_1x1), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": token},
    )
    file_key = up.get_json()["file_key"]
    resp = csrf_authed_client.delete(
        f"/sessions/upload/{file_key}", headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 204


def _csrf_token_from(client):
    """Fetch a CSRF token by visiting any GET-rendered form."""
    resp = client.get("/people/new")
    body = resp.get_data(as_text=True)
    # The token lives in <input type="hidden" name="csrf_token" value="...">
    import re
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    if m is None:
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', body)
    assert m is not None, "no CSRF token in rendered form"
    return m.group(1)
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_session_async_upload.py -v --no-cov`
Expected: 4 FAIL — endpoint doesn't exist (404).

- [ ] **Step 3: Implement the blueprint**

Create `flexlog/web/upload_bp.py`:

```python
"""AJAX endpoints for the progressive session-form upload flow.

POST /sessions/upload  — multipart, returns JSON with the file_key
DELETE /sessions/upload/<file_key> — best-effort orphan delete

Both require auth (gated by the global before_request) and CSRF (the
Flask-WTF default reads X-CSRFToken from request headers).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from flexlog.db import get_db
from flexlog.services.media import (
    MediaUploadError,
    UnsupportedMediaTypeError,
    orphan_delete_media_file,
    upload_to_media_file,
)

upload_bp = Blueprint("upload", __name__)

_KIND_TO_MEDIA_TYPE = {"photo": "photo", "audio": "audio", "video": "video"}


@upload_bp.post("/sessions/upload")
def upload():
    kind = (request.form.get("kind") or "").strip()
    if kind not in _KIND_TO_MEDIA_TYPE:
        return jsonify({"error": f"unknown kind {kind!r}"}), 422

    fs = request.files.get("file")
    if fs is None or fs.filename == "":
        return jsonify({"error": "no file uploaded"}), 422

    db = get_db()
    try:
        mf = upload_to_media_file(db, fs)
    except UnsupportedMediaTypeError as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 415
    except MediaUploadError as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 413

    if mf.media_type != _KIND_TO_MEDIA_TYPE[kind]:
        db.rollback()
        return jsonify({
            "error": f"file is a {mf.media_type}, not a {kind}",
        }), 422

    db.commit()
    return jsonify({
        "file_key": mf.file_key,
        "original_filename": mf.original_filename,
        "media_type": mf.media_type,
        "size_bytes": mf.file_size_bytes,
        "mime": mf.mime_type,
    })


@upload_bp.delete("/sessions/upload/<path:file_key>")
def upload_delete(file_key: str):
    db = get_db()
    orphan_delete_media_file(db, file_key)
    db.commit()
    return "", 204
```

In `flexlog/web/__init__.py`, register the new blueprint. Add the import:

```python
from flexlog.web.upload_bp import upload_bp
```

And add it inside `register_blueprints`:

```python
    app.register_blueprint(upload_bp)
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/integration/test_session_async_upload.py -v --no-cov`
Expected: 4 PASS.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: all green, coverage ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/web/upload_bp.py flexlog/web/__init__.py tests/integration/test_session_async_upload.py
git commit -m "upload: AJAX endpoints for progressive session-form uploads

POST /sessions/upload runs the multipart payload through the
existing upload_to_media_file pipeline (dedup, magic-byte check,
chunked AES-GCM encrypt). Returns JSON with the file_key.

DELETE /sessions/upload/<file_key> is best-effort orphan delete —
returns 204 whether or not the file actually went away (preserves
dedup hits silently).

Both authed + CSRF-protected via Flask-WTF (reads X-CSRFToken
from request headers)."
```

---

## Task 9: `sessions_bp` accepts `photo_keys[]`/`audio_keys[]`/`video_keys[]`/`unlinked_keys[]`

Wire the new helpers into create/update routes. After validating the form, route handlers call `link_media_to_session` and `unlink_media_from_session` based on hidden form arrays.

**Files:**
- Modify: `flexlog/web/sessions_bp.py`
- Test: `tests/integration/test_session_form_e2e.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_session_form_e2e.py`:

```python
"""End-to-end: upload via AJAX → submit the form referencing the file_keys
→ session lands with the right media joins + links."""
from __future__ import annotations

import io
import re

from tests.integration.test_session_async_upload import JPEG_1x1


def _csrf_token_from(client, path):
    body = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    return m.group(1)


def _upload(client, token, kind, fname, mime, content):
    resp = client.post(
        "/sessions/upload",
        data={"kind": kind, "file": (io.BytesIO(content), fname, mime)},
        content_type="multipart/form-data",
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["file_key"]


def test_create_session_with_uploaded_media_and_links(csrf_authed_client, person):
    token = _csrf_token_from(csrf_authed_client, f"/people/{person.id}/sessions/new")
    photo_key = _upload(csrf_authed_client, token, "photo", "p.jpg", "image/jpeg", JPEG_1x1)

    resp = csrf_authed_client.post(
        f"/people/{person.id}/sessions",
        data={
            "csrf_token": token,
            "session_date": "2026-01-01",
            "rating_energy": "4",
            "notes": "hello",
            "photo_keys": [photo_key],
            "audio_keys": [],
            "video_keys": [],
            "link_urls": ["https://example.com/a"],
        },
    )
    # Should redirect to the detail page.
    assert resp.status_code == 303

    # Hit the detail page; verify the link + photo render.
    detail = csrf_authed_client.get(resp.headers["Location"])
    body = detail.get_data(as_text=True)
    assert "https://example.com/a" in body
    assert "rating_energy" not in body  # form field doesn't leak
    assert "Energy" in body  # rating label rendered
```

This needs the `person` fixture against `csrf_authed_client` — extend the fixture in `tests/conftest.py` to be parameterizable, or add a parallel `csrf_person` fixture. Simplest: extend `person` to take its db_session from whichever client is active. Or — create the person inline. Let me make the fixture work both ways by making it lazily resolve the engine from `csrf_app`'s db_session if needed.

Simplest: just keep two fixtures, both reuse the same factory. Add to conftest.py:

```python
@pytest.fixture
def person(db_session):  # noqa: F811 — overrides if already declared
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Test", tag_input="")
    db_session.commit()
    return p
```

(If a `person` fixture already exists from Task 7, leave it alone — this is the same definition.)

But `db_session` depends on `app` (not `csrf_app`). For the CSRF test, the simplest path is to create the person within the test using the `csrf_app`'s engine. Add a fixture:

```python
@pytest.fixture
def csrf_db_session(csrf_app):
    from flexlog.db import close_db, get_db
    with csrf_app.app_context():
        s = get_db()
        try:
            yield s
        finally:
            close_db()


@pytest.fixture
def csrf_person(csrf_db_session):
    from flexlog.services.people import create_person
    p = create_person(csrf_db_session, alias="Test", tag_input="")
    csrf_db_session.commit()
    return p
```

Replace `person` with `csrf_person` in `test_create_session_with_uploaded_media_and_links`.

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_e2e.py -v --no-cov`
Expected: FAIL because the route ignores `photo_keys[]`.

- [ ] **Step 3: Update `create` + `update` to wire media linking**

In `flexlog/web/sessions_bp.py`, add the new parsing helper near the other `_parse_*` helpers:

```python
def _parse_keys_from_request() -> dict[str, list[str]]:
    return {
        "photo": request.form.getlist("photo_keys"),
        "audio": request.form.getlist("audio_keys"),
        "video": request.form.getlist("video_keys"),
    }


def _parse_unlinked_keys_from_request() -> list[str]:
    return request.form.getlist("unlinked_keys")
```

Update the imports near the top — add `link_media_to_session, unlink_media_from_session`:

```python
from flexlog.services.sessions import (
    SessionNotFoundError,
    create_session,
    delete_session,
    enabled_rating_dimensions,
    get_session,
    link_media_to_session,
    split_ratings,
    unlink_media_from_session,
    update_session,
)
```

In `create`, after `create_session(...)` and before `db.commit()`:

```python
    link_media_to_session(db, session_row.id, _parse_keys_from_request())
```

In `update`, after the `update_session(...)` call (still inside the try block) and before `db.commit()`:

```python
    unlink_media_from_session(db, session_id, _parse_unlinked_keys_from_request())
    link_media_to_session(db, session_id, _parse_keys_from_request())
```

- [ ] **Step 4: Run to verify passes**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_e2e.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: all green, coverage ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/web/sessions_bp.py tests/conftest.py tests/integration/test_session_form_e2e.py
git commit -m "sessions: wire create/update to link uploaded file_keys

The Save handler now reads photo_keys[]/audio_keys[]/video_keys[]
hidden inputs (file_keys produced by the AJAX upload endpoint)
and creates SessionMedia rows. Update additionally handles
unlinked_keys[] to remove existing joins."
```

---

## Task 10: Form template rewrite — pending-uploads UI, link UI, CSRF meta tag

Replace `flexlog/templates/sessions/_form_body.html` with the new layout: pending-list `<ul>` per media kind, single-input link row with Add button. Drop the `overall_score` `<input>` and the multi-row link form. Add the CSRF meta tag to `_base.html` so JS can read it.

**Files:**
- Modify: `flexlog/templates/_base.html`, `flexlog/templates/sessions/_form_body.html`
- Test: `tests/integration/test_session_form_template.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_session_form_template.py`:

```python
"""Smoke checks on the rewritten session form template."""
from __future__ import annotations


def test_new_form_has_csrf_meta_tag(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    assert '<meta name="csrf-token"' in body


def test_new_form_renders_per_kind_pending_lists(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    assert 'data-kind="photo"' in body
    assert 'data-kind="audio"' in body
    assert 'data-kind="video"' in body
    # Single-textbox link UI
    assert 'name="new_link_url"' in body
    # No legacy overall_score input
    assert 'name="overall_score"' not in body


def test_new_form_renders_rating_inputs_from_enabled_dims(authed_client, person):
    body = authed_client.get(f"/people/{person.id}/sessions/new").get_data(as_text=True)
    # Default config has the energy dimension
    assert 'name="rating_energy"' in body
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_template.py -v --no-cov`
Expected: FAIL — meta tag absent; legacy form still rendered.

- [ ] **Step 3: Add CSRF meta tag to `_base.html`**

Open `flexlog/templates/_base.html` and add inside `<head>` (any position works, but a common spot is just after `<title>` or right before `</head>`):

```html
<meta name="csrf-token" content="{{ csrf_token() }}">
```

- [ ] **Step 4: Rewrite `_form_body.html`**

Replace the entire file contents with:

```html
<div class="form-row">
  <label for="session_date">{{ "session_date_label" | ui }}</label>
  <input type="date" id="session_date" name="session_date" value="{{ form.session_date.data or '' }}" required>
  {% for err in form.session_date.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
</div>

{% if rating_dimensions %}
<fieldset class="form-row ratings-grid">
  <legend>{{ "ratings_heading" | ui }}</legend>
  {% for dim in rating_dimensions %}
    <div class="rating-input">
      <label for="rating_{{ dim.id }}">{{ dim.label }}</label>
      <input type="number" id="rating_{{ dim.id }}" name="rating_{{ dim.id }}"
             min="{{ dim.scale_min }}" max="{{ dim.scale_max }}" step="1"
             value="{{ existing_ratings.get(dim.id, '') }}">
    </div>
  {% endfor %}
</fieldset>
{% endif %}

<div class="form-row">
  <label for="notes">{{ "notes_label" | ui }}</label>
  <textarea id="notes" name="notes" rows="6">{{ form.notes.data or '' }}</textarea>
  {% for err in form.notes.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
</div>

{# Per-kind pending-uploads list. JS owns the list contents; the server
   reads the hidden <input name="<kind>_keys"> values on submit. #}
{% for kind, label_key, accept in [
     ('photo', 'photos_label', 'image/jpeg,image/png,image/webp'),
     ('audio', 'audio_label',  'audio/mpeg,audio/wav,audio/mp4,audio/x-m4a'),
     ('video', 'videos_label', 'video/mp4,video/webm,video/quicktime'),
] %}
<fieldset class="form-row media-uploads" data-kind="{{ kind }}">
  <legend>{{ label_key | ui }}</legend>
  <ul class="pending-list" data-pending-list>
    {% for mf in existing_media.get(kind, []) %}
      <li class="upload-row" data-status="uploaded" data-existing="true" data-file-key="{{ mf.file_key }}">
        <span class="upload-name">{{ mf.original_filename or mf.file_key }}</span>
        <span class="upload-status">✓</span>
        <button type="button" class="btn upload-remove" data-remove>✕</button>
        <input type="hidden" name="{{ kind }}_keys" value="{{ mf.file_key }}">
      </li>
    {% endfor %}
  </ul>
  <input type="file" class="upload-input" accept="{{ accept }}" multiple data-upload-input hidden>
  <button type="button" class="btn upload-add" data-upload-add>+ {{ label_key | ui }}</button>
</fieldset>
{% endfor %}

{# Track existing media that the user removed (their hidden <input> is
   deleted by JS, and the file_key is appended here so the server can
   call unlink_media_from_session). #}
<div data-unlinked-keys-container></div>

<fieldset class="form-row links-row">
  <legend>{{ "links_heading" | ui }}</legend>
  <ul class="link-list" data-link-list>
    {% for url in existing_link_urls %}
      <li class="link-row" data-link-row>
        <a href="{{ url }}" target="_blank" rel="noopener">{{ url }}</a>
        <button type="button" class="btn link-remove" data-link-remove>✕</button>
        <input type="hidden" name="link_urls" value="{{ url }}">
      </li>
    {% endfor %}
  </ul>
  <div class="link-add-row">
    <input type="url" id="new_link_url" name="new_link_url" placeholder="https://…" data-link-input>
    <button type="button" class="btn" data-link-add>+ {{ "add_link" | ui }}</button>
  </div>
  <p class="link-add-error" data-link-error hidden></p>
</fieldset>
```

The new template assumes `existing_media` is a dict keyed by `"photo"|"audio"|"video"` (each value a list of MediaFile rows) and `existing_link_urls` is a flat list of URL strings. The route handlers in Task 5 already produce these.

- [ ] **Step 5: Run new tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_template.py -v --no-cov`
Expected: 3 PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -5`
Expected: full suite green. (Tests that previously poked at `link_url[0]`-style fields will be in test files updated in Task 5 already; if any still expect the old form shape, fix them now.)

- [ ] **Step 6: Commit**

```bash
git add flexlog/templates/_base.html flexlog/templates/sessions/_form_body.html tests/integration/test_session_form_template.py
git commit -m "templates: rewrite session form for progressive uploads

Per-kind pending-uploads fieldset (data-kind=photo|audio|video)
with a hidden file input + 'Add' button. JS will append <li>
rows and hidden <input name=\"<kind>_keys\"> as uploads succeed.

Links UI collapses to one <input type=url> + Add button; the
list of added links lives above as data-link-row elements with
hidden <input name=\"link_urls\">.

CSRF token exposed via <meta name=\"csrf-token\"> in _base.html
so session_form.js can attach X-CSRFToken on every XHR."
```

---

## Task 11: `session_form.js` — XHR uploads, link Add, beforeunload, unlinked tracking

The behavior code behind the new form. Plain JS (no library). Read CSRF from the meta tag. Hooks: clicking `+ Add photos` triggers the hidden file input → on `change`, each File is uploaded via XHR with progress events. Successful uploads append a list row with hidden `<input>`. Remove button: for `data-existing="true"` rows, transfer the file_key to a hidden `<input name="unlinked_keys">` (server-side unlink); for new rows, fire `DELETE /sessions/upload/<file_key>` and remove the row. Link Add: validate URL parses → prepend to list. `beforeunload` fires only when any pending list has uploaded-but-unsaved new rows.

**Files:**
- Create: `flexlog/static/js/session_form.js`
- Test: covered by `test_session_form_e2e.py` (already created in Task 9 — that integration test exercises this path with form POSTs simulating what JS would submit). Plus a behavior smoke test below.

- [ ] **Step 1: Implement the JS module**

Create `flexlog/static/js/session_form.js`:

```javascript
"use strict";

// Read CSRF token once.
const CSRF =
  document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

let formSubmitting = false;

document.addEventListener("DOMContentLoaded", () => {
  bindMediaFieldsets();
  bindLinkSection();
  bindBeforeUnload();
  bindFormSubmit();
});

function bindMediaFieldsets() {
  for (const fs of document.querySelectorAll("fieldset[data-kind]")) {
    const kind = fs.dataset.kind;
    const fileInput = fs.querySelector("[data-upload-input]");
    const addBtn = fs.querySelector("[data-upload-add]");
    const list = fs.querySelector("[data-pending-list]");

    addBtn.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
      for (const file of fileInput.files) {
        uploadOne(kind, file, list);
      }
      fileInput.value = "";
    });

    list.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-remove]");
      if (btn) removeRow(btn.closest(".upload-row"), kind);
    });
  }
}

function uploadOne(kind, file, listEl) {
  const row = document.createElement("li");
  row.className = "upload-row";
  row.dataset.status = "uploading";
  row.innerHTML = `
    <span class="upload-name"></span>
    <span class="upload-status">
      <progress max="100" value="0" data-progress></progress>
    </span>
    <button type="button" class="btn upload-remove" data-remove>✕</button>
  `;
  row.querySelector(".upload-name").textContent = file.name;
  listEl.appendChild(row);

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/sessions/upload");
  xhr.setRequestHeader("X-CSRFToken", CSRF);
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = (e.loaded / e.total) * 100;
    row.querySelector("[data-progress]").value = pct;
  };
  xhr.onload = () => {
    if (xhr.status !== 200) {
      markFailed(row, parseError(xhr));
      return;
    }
    const j = JSON.parse(xhr.responseText);
    markUploaded(row, kind, j);
  };
  xhr.onerror = () => markFailed(row, "network error");
  xhr.onabort = () => markFailed(row, "aborted");

  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("file", file);
  xhr.send(fd);
}

function markUploaded(row, kind, payload) {
  row.dataset.status = "uploaded";
  row.dataset.fileKey = payload.file_key;
  row.querySelector(".upload-status").textContent = "✓";
  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.name = `${kind}_keys`;
  hidden.value = payload.file_key;
  row.appendChild(hidden);
}

function markFailed(row, msg) {
  row.dataset.status = "failed";
  row.querySelector(".upload-status").textContent = "✗ " + msg;
}

function parseError(xhr) {
  try {
    return JSON.parse(xhr.responseText).error || `HTTP ${xhr.status}`;
  } catch {
    return `HTTP ${xhr.status}`;
  }
}

function removeRow(row, kind) {
  const fileKey = row.dataset.fileKey;
  const existing = row.dataset.existing === "true";

  if (existing && fileKey) {
    // Don't delete server-side. Transfer the key to unlinked_keys[] so the
    // Save handler unlinks it from the session at form submit.
    const container = document.querySelector("[data-unlinked-keys-container]");
    const hid = document.createElement("input");
    hid.type = "hidden";
    hid.name = "unlinked_keys";
    hid.value = fileKey;
    container.appendChild(hid);
    row.remove();
    return;
  }

  if (fileKey) {
    // Best-effort server-side delete; UI removes regardless of result.
    fetch(`/sessions/upload/${encodeURIComponent(fileKey)}`, {
      method: "DELETE",
      headers: { "X-CSRFToken": CSRF },
    }).catch(() => {});
  }
  row.remove();
}

function bindLinkSection() {
  const list = document.querySelector("[data-link-list]");
  const input = document.querySelector("[data-link-input]");
  const addBtn = document.querySelector("[data-link-add]");
  const errEl = document.querySelector("[data-link-error]");
  if (!list || !input || !addBtn) return;

  const addLink = () => {
    const raw = input.value.trim();
    errEl.hidden = true;
    if (!raw) return;
    try {
      const u = new URL(raw);
      if (!u.protocol || !u.host) throw new Error("missing host");
    } catch {
      errEl.textContent = "Invalid URL — include http:// or https://";
      errEl.hidden = false;
      return;
    }
    const li = document.createElement("li");
    li.className = "link-row";
    li.dataset.linkRow = "";
    const a = document.createElement("a");
    a.href = raw;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = raw;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn link-remove";
    btn.dataset.linkRemove = "";
    btn.textContent = "✕";
    const hid = document.createElement("input");
    hid.type = "hidden";
    hid.name = "link_urls";
    hid.value = raw;
    li.append(a, btn, hid);
    list.appendChild(li);
    input.value = "";
  };

  addBtn.addEventListener("click", addLink);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addLink();
    }
  });
  list.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-link-remove]");
    if (btn) btn.closest("[data-link-row]").remove();
  });
}

function hasUnsavedUploads() {
  for (const row of document.querySelectorAll(
    ".upload-row:not([data-existing='true'])"
  )) {
    if (row.dataset.status === "uploaded" || row.dataset.status === "uploading") {
      return true;
    }
  }
  return false;
}

function hasUploadingRows() {
  return !!document.querySelector(".upload-row[data-status='uploading']");
}

function bindBeforeUnload() {
  window.addEventListener("beforeunload", (e) => {
    if (formSubmitting) return;
    if (hasUnsavedUploads()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

function bindFormSubmit() {
  const form = document.querySelector("form.session-form");
  if (!form) return;
  form.addEventListener("submit", (e) => {
    if (hasUploadingRows()) {
      e.preventDefault();
      alert("Wait for uploads to finish before saving.");
      return;
    }
    formSubmitting = true;
  });
}
```

- [ ] **Step 2: Smoke test that the file is served**

Add to `tests/integration/test_session_form_template.py`:

```python
def test_session_form_js_is_served(authed_client):
    resp = authed_client.get("/static/js/session_form.js")
    assert resp.status_code == 200
    assert b"uploadOne" in resp.data
```

Run: `.venv/bin/python -m pytest tests/integration/test_session_form_template.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 4: Manual browser smoke**

Start the dev server and verify the flow in a browser:

```bash
make dev
```

In the browser: log in → visit `/people/<id>/sessions/new` → click "+ Photos" → pick a JPEG → watch the progress bar fill → row goes ✓ → click ✕ → row disappears → Add a URL, click Add → row appears with the link → Save → redirected to detail.

If the manual smoke surfaces a bug, fix and re-run the suite before committing.

- [ ] **Step 5: Commit**

```bash
git add flexlog/static/js/session_form.js tests/integration/test_session_form_template.py
git commit -m "session_form.js: progressive upload + link UI

XHR-driven upload with real progress bars; CSRF via X-CSRFToken
header (read once from <meta name=csrf-token>). Remove button
handles existing-media (transfer to unlinked_keys[]) and new
uploads (server DELETE + remove row). Link Add validates URL
parse; Enter == click Add. beforeunload fires only when there's
an uploaded-but-unsaved row, and submit blocks while any row is
still uploading."
```

---

## Task 12: Detail page reorder + audio download anchor removed

Sections from top to bottom: Links → Ratings → Notes → Audio → Photos → Videos. Empty sections collapse. Audio template drops the `<a class="audio-download">` anchor.

**Files:**
- Modify: `flexlog/templates/sessions/detail.html`, `flexlog/templates/_partials/media_audio.html`, `flexlog/static/css/main.css`
- Test: `tests/integration/test_detail_order.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_detail_order.py`:

```python
"""Detail page sections render in the new order and the audio template
has no download link."""
from __future__ import annotations

import io

from tests.integration.test_session_async_upload import JPEG_1x1


def test_detail_section_order(authed_client, person, db_session):
    from flexlog.services.sessions import create_session, link_media_to_session
    from flexlog.services.media import upload_to_media_file
    from werkzeug.datastructures import FileStorage

    s = create_session(
        db_session, person_id=person.id, session_date="2026-01-01",
        ratings={"energy": 3}, notes="my notes here",
        link_urls=["https://example.com/x"],
    )
    db_session.flush()
    photo = upload_to_media_file(
        db_session,
        FileStorage(stream=io.BytesIO(JPEG_1x1), filename="t.jpg", content_type="image/jpeg"),
    )
    link_media_to_session(db_session, s.id, {"photo": [photo.file_key], "audio": [], "video": []})
    db_session.commit()

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)

    # Section anchors (h3 text we ship in the template)
    i_links = body.find("links-display")
    i_ratings = body.find("ratings-display")
    i_notes = body.find("notes-display")
    i_audio = body.find("audios-section")
    i_photos = body.find("photos-section")
    i_videos = body.find("videos-section")

    # Required sections always present; media sections only when present.
    assert i_links >= 0 and i_ratings >= 0 and i_notes >= 0
    assert i_photos >= 0  # we attached a photo
    # Order check (use a sentinel for sections that may be -1):
    SENT = 1 << 30
    order = [
        i_links,
        i_ratings,
        i_notes,
        i_audio if i_audio >= 0 else SENT,
        i_photos,
        i_videos if i_videos >= 0 else SENT,
    ]
    # Filter out SENT entries before checking ascending order
    real = [v for v in order if v != SENT]
    assert real == sorted(real)


def test_audio_template_has_no_download_link():
    from pathlib import Path
    body = Path("flexlog/templates/_partials/media_audio.html").read_text()
    assert "audio-download" not in body
    assert 'class="audio-download"' not in body
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_detail_order.py -v --no-cov`
Expected: FAIL — current order is Ratings → Notes → Photos → Audio → Videos → Links.

- [ ] **Step 3: Reorder `detail.html`**

Replace `flexlog/templates/sessions/detail.html` contents with:

```html
{% extends "_base.html" %}

{% block title %}{{ session.session_date }} — {{ person.alias }}{% endblock %}

{% block content %}
<section class="session-detail">
  <header class="session-detail-header">
    <p class="breadcrumb"><a href="{{ url_for('people.detail', person_id=person.id) }}">{{ person.alias }}</a></p>
    <h2>{{ session.session_date }}</h2>
    <div class="session-detail-actions">
      <a class="btn" href="{{ url_for('sessions.edit', session_id=session.id) }}">{{ "edit_session" | ui }}</a>
    </div>
  </header>

  <section class="links-display">
    <h3>{{ "links_heading" | ui }}</h3>
    {% if session.links %}
      <ul class="link-list">
        {% for link in session.links %}
          {% include "_partials/link_row_display.html" %}
        {% endfor %}
      </ul>
    {% else %}
      <p class="empty-state">{{ "no_links" | ui }}</p>
    {% endif %}
  </section>

  <section class="ratings-display">
    <h3>{{ "ratings_heading" | ui }}</h3>
    {% if current_ratings %}
      <ul>
        {% for rid, label, value in current_ratings %}
          <li>{{ label }}: <strong>{{ value }}</strong></li>
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

  {% if session.notes %}
  <section class="notes-display">
    <h3>{{ "notes_label" | ui }}</h3>
    <pre class="notes">{{ session.notes }}</pre>
  </section>
  {% endif %}

  {% if audios %}
  <section class="media-section audios-section">
    <h3>{{ "audio_label" | ui }}</h3>
    <ul class="audio-list">
      {% for media in audios %}
        {% include "_partials/media_audio.html" %}
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  {% if photos %}
  <section class="media-section photos-section">
    <h3>{{ "photos_label" | ui }}</h3>
    <div id="photo-gallery" class="photo-grid">
      {% for media in photos %}
        {% include "_partials/media_photo_thumb.html" %}
      {% endfor %}
    </div>
  </section>
  {% endif %}

  {% if videos %}
  <section class="media-section videos-section">
    <h3>{{ "videos_label" | ui }}</h3>
    <ul class="video-list">
      {% for media in videos %}
        {% include "_partials/media_video.html" %}
      {% endfor %}
    </ul>
  </section>
  {% endif %}
</section>

<link rel="stylesheet" href="{{ url_for('static', filename='vendor/photoswipe/photoswipe.css') }}">
<script src="{{ url_for('static', filename='vendor/photoswipe/photoswipe.umd.min.js') }}" defer></script>
<script src="{{ url_for('static', filename='vendor/photoswipe/photoswipe-lightbox.umd.min.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/photoswipe_init.js') }}" defer></script>
{% endblock %}
```

- [ ] **Step 4: Drop the audio download anchor**

Replace `flexlog/templates/_partials/media_audio.html` with:

```html
<li class="audio-item">
  <audio controls preload="metadata" src="{{ url_for('media.serve', file_key=media.file_key) }}"></audio>
  <span class="audio-name">{{ media.original_filename or media.file_key }}</span>
</li>
```

- [ ] **Step 5: Drop the `.audio-download` CSS rule**

In `flexlog/static/css/main.css`, find the `.audio-download` rule(s) and delete them. (If none exists, skip.)

Run: `grep -n "audio-download" flexlog/static/css/main.css`
Delete every matching block; selectors `.audio-download` (any variant).

- [ ] **Step 6: Add the new UI string keys**

The detail page references `ratings_heading`, `no_ratings`, `archived_ratings_heading`. Some may already exist; add the missing ones to `flexlog/web/filters.py:BUILTIN_UI_DEFAULTS`. Open that file and ensure entries exist for:

```python
"ratings_heading": "Ratings",
"no_ratings": "No ratings yet.",
"archived_ratings_heading": "Archived ratings",
"add_link": "Add link",
"no_links": "No links.",
```

(If they already exist, leave them.)

- [ ] **Step 7: Run new tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_detail_order.py -v --no-cov`
Expected: PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 8: Commit**

```bash
git add flexlog/templates/sessions/detail.html flexlog/templates/_partials/media_audio.html flexlog/static/css/main.css flexlog/web/filters.py tests/integration/test_detail_order.py
git commit -m "detail: reorder sections + drop audio download anchor

New order: Links → Ratings → Notes → Audio → Photos → Videos.
Empty sections collapse. Audio is streamed inline via <audio
controls>; the redundant Download anchor is gone (right-click
save-as on the audio element still works for users who really
want a file)."
```

---

## Task 13: Settings page — base template + `GET /settings` + App tab POST

Lay the foundation: the page with five tabs, the GET handler that renders any tab, the POST handler for the simplest tab (App). Subsequent tasks add the other tabs.

**Files:**
- Modify: `flexlog/web/settings_bp.py`, `flexlog/templates/settings/index.html`
- Create: `flexlog/templates/settings/_app.html`, `_ratings.html` (stub), `_ui_strings.html` (stub), `_limits.html` (stub), `_raw.html` (stub)
- Test: `tests/integration/test_settings_routes.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_settings_routes.py`:

```python
"""GET /settings + POST /settings/app pipeline.

Other tabs are covered by tests in subsequent tasks, but the base
page rendering is asserted here."""
from __future__ import annotations

import json
import re
from pathlib import Path


def _csrf_token(client, path="/settings"):
    body = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
    assert m is not None
    return m.group(1)


def test_settings_page_renders_all_five_tabs(authed_client):
    body = authed_client.get("/settings").get_data(as_text=True)
    for tab in ("app", "ratings", "ui_strings", "limits", "raw"):
        assert f"settings-tab-{tab}" in body  # tab nav link or panel


def test_settings_app_tab_save_persists(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    resp = csrf_authed_client.post(
        "/settings/app",
        data={
            "csrf_token": token,
            "name": "Renamed App",
            "entity_singular": "Subject",
            "entity_plural": "Subjects",
            "session_singular": "Meeting",
            "session_plural": "Meetings",
        },
    )
    assert resp.status_code == 303
    cfg_path = tmp_data_dir / "config.json"
    cfg = json.loads(cfg_path.read_text())
    assert cfg["app"]["name"] == "Renamed App"
    assert cfg["app"]["entity_singular"] == "Subject"


def test_settings_app_tab_rejects_invalid(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client)
    original = (tmp_data_dir / "config.json").read_text()
    resp = csrf_authed_client.post(
        "/settings/app",
        data={
            "csrf_token": token,
            "name": "",  # invalid — required
            "entity_singular": "Subject",
            "entity_plural": "Subjects",
            "session_singular": "Meeting",
            "session_plural": "Meetings",
        },
    )
    assert resp.status_code == 400
    # config.json untouched
    assert (tmp_data_dir / "config.json").read_text() == original
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py -v --no-cov`
Expected: FAIL — `/settings/app` doesn't exist; page lacks tab markers.

- [ ] **Step 3: Implement the GET handler + tab nav**

Rewrite `flexlog/web/settings_bp.py` — keep the existing `change_password` and `reload` handlers, but replace the `index` GET handler. Add the App POST handler too. The full new file (replacing the existing one):

```python
"""Settings page — GET renders the page with any tab; per-section POST
handlers validate + persist atomically.

Five tabs: app, ratings, ui_strings, limits, raw. Each tab is rendered
in its own partial. The GET handler delegates to the partial based on
?tab=<name>. POST handlers validate the merged config dict via
validate_config_dict and write atomically (mode 0600 tmp + rename).
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select

from flexlog import paths
from flexlog.config_loader import (
    ConfigError,
    DEFAULT_CONFIG_JSON,
    load_or_bootstrap,
    validate_config_dict,
)
from flexlog.crypto import (
    ARGON2_DEFAULT_PARAMS,
    Argon2Params,
    InvalidPassword,
    aes_gcm_unwrap,
    aes_gcm_wrap,
    argon2id_kek,
)
from flexlog.kdf_params import KdfParams, load_kdf_params, write_kdf_params
from flexlog.web.filters import ui_filter

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

_PASSWORD_MIN_LEN = 8
_VALID_TABS = ("app", "ratings", "ui_strings", "limits", "raw")


def _config_as_dict() -> dict:
    """Serialize the live Config dataclass back to a JSON-ready dict."""
    cfg = current_app.config["FLEXLOG"]
    return {
        "schema_version": 2,
        "app": asdict(cfg.app),
        "ratings": [
            {
                "id": r.id, "label": r.label, "description": r.description,
                "scale_min": r.scale_min, "scale_max": r.scale_max,
                "enabled": r.enabled, "sortable": r.sortable,
            }
            for r in cfg.ratings
        ],
        "ui_strings": dict(cfg.ui_strings),
        "limits": asdict(cfg.limits),
    }


def _atomic_write_config(merged: dict) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f".{path.name}.tmp.{secrets.token_hex(8)}"
    tmp = path.parent / tmp_name
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _in_use_rating_ids() -> set[str]:
    """The set of rating ids that appear in any session.ratings_json. Used to
    block rename/id-change conflicts."""
    from flexlog.db import get_db
    from flexlog.db.models import Session as SessionRow

    db = get_db()
    out: set[str] = set()
    for (raw,) in db.execute(select(SessionRow.ratings_json)).all():
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict):
            out.update(k for k in d.keys() if isinstance(k, str))
    return out


def _persist_and_swap(merged: dict, errors_redir_tab: str):
    """Validate -> write -> swap live config. Returns a Flask response on
    failure (re-render with errors) or None on success."""
    cfg, errors = validate_config_dict(merged)
    if errors:
        return render_template(
            "settings/index.html",
            tab=errors_redir_tab,
            config_dict=merged,
            errors=errors,
            in_use_ids=_in_use_rating_ids(),
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400
    _atomic_write_config(merged)
    current_app.config["FLEXLOG"] = cfg
    current_app.config["FLEXLOG_LOADED_AT"] = datetime.now(timezone.utc)
    flash("Settings saved.", "success")
    return None


@settings_bp.get("")
def index():
    tab = request.args.get("tab", "app")
    if tab not in _VALID_TABS:
        tab = "app"
    return render_template(
        "settings/index.html",
        tab=tab,
        config_dict=_config_as_dict(),
        errors=[],
        in_use_ids=_in_use_rating_ids(),
        config_path=str(paths.config_path()),
        loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
    )


@settings_bp.post("/app")
def save_app():
    merged = _config_as_dict()
    merged["app"] = {
        "name": (request.form.get("name") or "").strip(),
        "entity_singular": (request.form.get("entity_singular") or "").strip(),
        "entity_plural": (request.form.get("entity_plural") or "").strip(),
        "session_singular": (request.form.get("session_singular") or "").strip(),
        "session_plural": (request.form.get("session_plural") or "").strip(),
    }
    result = _persist_and_swap(merged, errors_redir_tab="app")
    if result is not None:
        return result
    return redirect(url_for("settings.index", tab="app"), code=303)


@settings_bp.post("/reload")
def reload():
    try:
        new_cfg = load_or_bootstrap(paths.config_path())
    except ConfigError as exc:
        flash(f"{ui_filter('config_reload_failed')}: {exc}", "error")
        return redirect(url_for("settings.index"), code=303)
    current_app.config["FLEXLOG"] = new_cfg
    current_app.config["FLEXLOG_LOADED_AT"] = datetime.now(timezone.utc)
    flash(ui_filter("config_reload_succeeded"), "success")
    return redirect(url_for("settings.index"), code=303)


@settings_bp.post("/change-password")
def change_password():
    # ... (unchanged from existing implementation — keep verbatim)
    if not current_app.config.get("MASTER_KEY"):
        abort(403)
    current = request.form.get("current_password", "")
    new1 = request.form.get("new_password", "")
    new2 = request.form.get("new_password_confirm", "")
    if not new1 or len(new1) < _PASSWORD_MIN_LEN:
        flash(f"New password must be at least {_PASSWORD_MIN_LEN} characters.", "error")
        return redirect(url_for("settings.index"), code=303)
    if new1 != new2:
        flash("New password and confirmation must match.", "error")
        return redirect(url_for("settings.index"), code=303)
    kdf_path = paths.data_dir() / "kdf_params.json"
    kdf = load_kdf_params(kdf_path)
    if kdf is None:
        abort(500)
    params = Argon2Params(kdf.argon2_time, kdf.argon2_memory_kib, kdf.argon2_parallelism)
    old_kek = argon2id_kek(current, kdf.kek_salt, params)
    try:
        unwrapped = aes_gcm_unwrap(old_kek, kdf.kek_nonce, kdf.wrapped_master_key)
    except InvalidPassword:
        flash("Current password is incorrect.", "error")
        return redirect(url_for("settings.index"), code=303)
    if unwrapped != current_app.config["MASTER_KEY"]:
        flash("Internal consistency error. Refusing to change password.", "error")
        return redirect(url_for("settings.index"), code=303)
    new_kek_salt = os.urandom(16)
    new_kek_nonce = os.urandom(12)
    new_kek = argon2id_kek(new1, new_kek_salt, ARGON2_DEFAULT_PARAMS)
    new_wrapped = aes_gcm_wrap(new_kek, new_kek_nonce, current_app.config["MASTER_KEY"])
    write_kdf_params(
        kdf_path,
        KdfParams(
            version=1, kek_salt=new_kek_salt, kek_nonce=new_kek_nonce,
            wrapped_master_key=new_wrapped,
            argon2_time=ARGON2_DEFAULT_PARAMS.time_cost,
            argon2_memory_kib=ARGON2_DEFAULT_PARAMS.memory_kib,
            argon2_parallelism=ARGON2_DEFAULT_PARAMS.parallelism,
        ),
    )
    flash("Password changed.", "success")
    return redirect(url_for("settings.index"), code=303)
```

- [ ] **Step 4: Rewrite the base settings template**

Replace `flexlog/templates/settings/index.html`:

```html
{% extends "_base.html" %}

{% block title %}{{ "settings" | ui }} — {{ labels.app_name }}{% endblock %}

{% block content %}
<section class="settings-page">
  <h2>{{ "settings" | ui }}</h2>

  {% if errors %}
  <div class="settings-errors">
    <p><strong>Could not save:</strong></p>
    <ul>{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
  </div>
  {% endif %}

  <nav class="settings-tabs">
    <a id="settings-tab-app" href="{{ url_for('settings.index', tab='app') }}" {% if tab == 'app' %}class="active"{% endif %}>App</a>
    <a id="settings-tab-ratings" href="{{ url_for('settings.index', tab='ratings') }}" {% if tab == 'ratings' %}class="active"{% endif %}>Ratings</a>
    <a id="settings-tab-ui_strings" href="{{ url_for('settings.index', tab='ui_strings') }}" {% if tab == 'ui_strings' %}class="active"{% endif %}>UI strings</a>
    <a id="settings-tab-limits" href="{{ url_for('settings.index', tab='limits') }}" {% if tab == 'limits' %}class="active"{% endif %}>Limits</a>
    <a id="settings-tab-raw" href="{{ url_for('settings.index', tab='raw') }}" {% if tab == 'raw' %}class="active"{% endif %}>Raw JSON</a>
  </nav>

  <div class="settings-tab-content">
    {% if tab == 'app' %}{% include "settings/_app.html" %}
    {% elif tab == 'ratings' %}{% include "settings/_ratings.html" %}
    {% elif tab == 'ui_strings' %}{% include "settings/_ui_strings.html" %}
    {% elif tab == 'limits' %}{% include "settings/_limits.html" %}
    {% elif tab == 'raw' %}{% include "settings/_raw.html" %}
    {% endif %}
  </div>
</section>

<section class="settings-page" style="margin-top:3rem">
  <h3>{{ "config_path_label" | ui }}</h3>
  <p><code>{{ config_path }}</code> · last loaded {{ loaded_at.strftime("%Y-%m-%d %H:%M:%S UTC") if loaded_at else "—" }}</p>
  <form method="post" action="{{ url_for('settings.reload') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <button type="submit" class="btn">{{ "reload_config" | ui }}</button>
  </form>
</section>

<section class="settings-page" style="margin-top:3rem">
  <h3>{{ "change_password_heading" | ui }}</h3>
  <form method="post" action="{{ url_for('settings.change_password') }}" class="person-form" autocomplete="off">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <div class="form-row">
      <label for="current_password">{{ "current_password_label" | ui }}</label>
      <input id="current_password" type="password" name="current_password" required>
    </div>
    <div class="form-row">
      <label for="new_password">{{ "new_password_label" | ui }}</label>
      <input id="new_password" type="password" name="new_password" required minlength="8">
    </div>
    <div class="form-row">
      <label for="new_password_confirm">{{ "new_password_confirm_label" | ui }}</label>
      <input id="new_password_confirm" type="password" name="new_password_confirm" required minlength="8">
    </div>
    <div class="form-actions">
      <button type="submit" class="btn btn-primary">{{ "change_password_submit" | ui }}</button>
    </div>
  </form>
</section>

<script src="{{ url_for('static', filename='js/settings.js') }}" defer></script>
{% endblock %}
```

- [ ] **Step 5: Implement the App tab partial**

Create `flexlog/templates/settings/_app.html`:

```html
<form method="post" action="{{ url_for('settings.save_app') }}" class="settings-form">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <div class="form-row">
    <label for="app_name">App name</label>
    <input id="app_name" type="text" name="name" value="{{ config_dict.app.name }}" required>
  </div>
  <div class="form-row">
    <label for="app_es">Entity (singular)</label>
    <input id="app_es" type="text" name="entity_singular" value="{{ config_dict.app.entity_singular }}" required>
  </div>
  <div class="form-row">
    <label for="app_ep">Entity (plural)</label>
    <input id="app_ep" type="text" name="entity_plural" value="{{ config_dict.app.entity_plural }}" required>
  </div>
  <div class="form-row">
    <label for="app_ss">Session (singular)</label>
    <input id="app_ss" type="text" name="session_singular" value="{{ config_dict.app.session_singular }}" required>
  </div>
  <div class="form-row">
    <label for="app_sp">Session (plural)</label>
    <input id="app_sp" type="text" name="session_plural" value="{{ config_dict.app.session_plural }}" required>
  </div>
  <div class="form-actions">
    <button type="submit" class="btn btn-primary">Save</button>
  </div>
</form>
```

Create empty placeholder partials so the include doesn't 500 — `_ratings.html`, `_ui_strings.html`, `_limits.html`, `_raw.html` each containing a single line:

```html
<p class="empty-state">Coming soon (task in progress).</p>
```

- [ ] **Step 6: Run new tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py -v --no-cov`
Expected: 3 PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: full suite green, ≥85%.

- [ ] **Step 7: Commit**

```bash
git add flexlog/web/settings_bp.py flexlog/templates/settings/index.html flexlog/templates/settings/_app.html flexlog/templates/settings/_ratings.html flexlog/templates/settings/_ui_strings.html flexlog/templates/settings/_limits.html flexlog/templates/settings/_raw.html tests/integration/test_settings_routes.py
git commit -m "settings: base page with five tabs + App tab POST

GET /settings?tab=<name> renders one of five tabs in a shared
layout. POST /settings/app validates app-labels block via
validate_config_dict, writes atomically (0600 tmp + rename),
and swaps current_app.config['FLEXLOG'] so labels update without
restart. Errors re-render the active tab with field-level
messages and never touch config.json on disk."
```

---

## Task 14: Settings — UI strings tab POST + Limits tab POST

The two simpler tabs after App. UI strings tab edits the dict in `cfg.ui_strings`; Limits tab edits the integer settings.

**Files:**
- Modify: `flexlog/web/settings_bp.py`, `flexlog/templates/settings/_ui_strings.html`, `flexlog/templates/settings/_limits.html`
- Test: extend `tests/integration/test_settings_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/integration/test_settings_routes.py`:

```python
def test_settings_ui_strings_save(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=ui_strings")
    resp = csrf_authed_client.post(
        "/settings/ui_strings",
        data={
            "csrf_token": token,
            "key": ["new_person", "add_session", "search_placeholder", "empty_dashboard"],
            "value": ["+ Guest", "+ Interview", "Find guests…", "Empty."],
        },
    )
    assert resp.status_code == 303
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert cfg["ui_strings"]["new_person"] == "+ Guest"


def test_settings_limits_save(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=limits")
    resp = csrf_authed_client.post(
        "/settings/limits",
        data={
            "csrf_token": token,
            "max_custom_rating_dimensions": "6",
            "max_audio_files_per_session": "5",
            "max_video_files_per_session": "5",
            "max_photo_files_per_session": "25",
            "max_upload_mb_per_file": "1000",
        },
    )
    assert resp.status_code == 303
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert cfg["limits"]["max_audio_files_per_session"] == 5
    assert cfg["limits"]["max_upload_mb_per_file"] == 1000
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py::test_settings_ui_strings_save tests/integration/test_settings_routes.py::test_settings_limits_save -v --no-cov`
Expected: 404 — routes don't exist.

- [ ] **Step 3: Add POST handlers**

Append to `flexlog/web/settings_bp.py`:

```python
@settings_bp.post("/ui_strings")
def save_ui_strings():
    merged = _config_as_dict()
    keys = request.form.getlist("key")
    values = request.form.getlist("value")
    new_strings: dict[str, str] = {}
    for k, v in zip(keys, values):
        k = (k or "").strip()
        if k:
            new_strings[k] = v
    merged["ui_strings"] = new_strings
    result = _persist_and_swap(merged, errors_redir_tab="ui_strings")
    if result is not None:
        return result
    return redirect(url_for("settings.index", tab="ui_strings"), code=303)


@settings_bp.post("/limits")
def save_limits():
    merged = _config_as_dict()
    fields = (
        "max_custom_rating_dimensions",
        "max_audio_files_per_session",
        "max_video_files_per_session",
        "max_photo_files_per_session",
        "max_upload_mb_per_file",
    )
    new_limits = {}
    for f in fields:
        raw = (request.form.get(f) or "").strip()
        try:
            new_limits[f] = int(raw)
        except ValueError:
            new_limits[f] = raw  # let validator reject it
    merged["limits"] = new_limits
    result = _persist_and_swap(merged, errors_redir_tab="limits")
    if result is not None:
        return result
    return redirect(url_for("settings.index", tab="limits"), code=303)
```

- [ ] **Step 4: Implement the partials**

Replace `flexlog/templates/settings/_ui_strings.html`:

```html
<form method="post" action="{{ url_for('settings.save_ui_strings') }}" class="settings-form">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <p class="form-hint">Key/value pairs of UI string overrides. Empty rows are dropped.</p>
  <table class="ui-strings-table">
    <thead><tr><th>Key</th><th>Value</th></tr></thead>
    <tbody data-ui-strings-tbody>
      {% for k, v in config_dict.ui_strings.items() %}
      <tr>
        <td><input type="text" name="key" value="{{ k }}"></td>
        <td><input type="text" name="value" value="{{ v }}"></td>
      </tr>
      {% endfor %}
      <tr>
        <td><input type="text" name="key" placeholder="new key"></td>
        <td><input type="text" name="value" placeholder="new value"></td>
      </tr>
    </tbody>
  </table>
  <div class="form-actions">
    <button type="submit" class="btn btn-primary">Save</button>
  </div>
</form>
```

Replace `flexlog/templates/settings/_limits.html`:

```html
<form method="post" action="{{ url_for('settings.save_limits') }}" class="settings-form">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  {% for f, label in [
      ('max_custom_rating_dimensions', 'Max custom rating dimensions'),
      ('max_audio_files_per_session', 'Max audio files / session'),
      ('max_video_files_per_session', 'Max video files / session'),
      ('max_photo_files_per_session', 'Max photo files / session'),
      ('max_upload_mb_per_file', 'Max upload size (MB / file)'),
  ] %}
  <div class="form-row">
    <label for="lim_{{ f }}">{{ label }}</label>
    <input id="lim_{{ f }}" type="number" min="1" name="{{ f }}" value="{{ config_dict.limits[f] }}" required>
  </div>
  {% endfor %}
  <div class="form-actions">
    <button type="submit" class="btn btn-primary">Save</button>
  </div>
</form>
```

- [ ] **Step 5: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py -v --no-cov`
Expected: all PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: full suite green, ≥85%.

- [ ] **Step 6: Commit**

```bash
git add flexlog/web/settings_bp.py flexlog/templates/settings/_ui_strings.html flexlog/templates/settings/_limits.html tests/integration/test_settings_routes.py
git commit -m "settings: UI strings + Limits tabs

UI strings tab persists a key/value table (blanks dropped).
Limits tab edits the five integer file/rating caps. Both
follow the same validate-then-atomic-write pipeline as App."
```

---

## Task 15: Settings — Ratings tab POST + Raw JSON tab POST + in-use id rename protection

The ratings tab is the most involved: dynamic rating-row entries, server-side enforcement that an id can't be changed if any session row references it.

**Files:**
- Modify: `flexlog/web/settings_bp.py`, `flexlog/templates/settings/_ratings.html`, `flexlog/templates/settings/_raw.html`
- Test: extend `tests/integration/test_settings_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/integration/test_settings_routes.py`:

```python
def test_settings_ratings_add_dimension(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=ratings")
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            # Repeating-row schema: each row has id, label, scale_min, scale_max,
            # enabled, sortable form fields. Position in the list matches order.
            "rating_id": ["energy", "focus"],
            "rating_label": ["Energy", "Focus"],
            "rating_description": ["How energetic", "How focused"],
            "rating_scale_min": ["0", "0"],
            "rating_scale_max": ["5", "10"],
            "rating_enabled": ["energy", "focus"],
            "rating_sortable": ["energy"],
        },
    )
    assert resp.status_code == 303
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert [r["id"] for r in cfg["ratings"]] == ["energy", "focus"]
    assert cfg["ratings"][1]["scale_max"] == 10
    # 'focus' wasn't in rating_sortable → sortable=False
    assert cfg["ratings"][1]["sortable"] is False


def test_settings_ratings_rename_blocked_if_in_use(csrf_authed_client, tmp_data_dir, db_session, person):
    from flexlog.services.sessions import create_session
    create_session(
        db_session, person_id=person.id, session_date="2026-01-01",
        ratings={"energy": 4}, notes=None, link_urls=[],
    )
    db_session.commit()

    token = _csrf_token(csrf_authed_client, "/settings?tab=ratings")
    resp = csrf_authed_client.post(
        "/settings/ratings",
        data={
            "csrf_token": token,
            # Attempt to rename 'energy' → 'vigor' while a session still has
            # a rating under 'energy'.
            "rating_id": ["vigor"],
            "rating_label": ["Vigor"],
            "rating_description": [""],
            "rating_scale_min": ["0"],
            "rating_scale_max": ["5"],
            "rating_enabled": ["vigor"],
            "rating_sortable": ["vigor"],
        },
    )
    assert resp.status_code == 400  # validation rejected
    # config.json untouched
    cfg = json.loads(Path(tmp_data_dir, "config.json").read_text())
    assert cfg["ratings"][0]["id"] == "energy"


def test_settings_raw_json_save(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=raw")
    new_cfg = json.loads((tmp_data_dir / "config.json").read_text())
    new_cfg["app"]["name"] = "From Raw"
    resp = csrf_authed_client.post(
        "/settings/raw",
        data={"csrf_token": token, "raw_json": json.dumps(new_cfg, indent=2)},
    )
    assert resp.status_code == 303
    cfg = json.loads((tmp_data_dir / "config.json").read_text())
    assert cfg["app"]["name"] == "From Raw"


def test_settings_raw_json_rejects_bad_json(csrf_authed_client, tmp_data_dir):
    token = _csrf_token(csrf_authed_client, "/settings?tab=raw")
    original = (tmp_data_dir / "config.json").read_text()
    resp = csrf_authed_client.post(
        "/settings/raw",
        data={"csrf_token": token, "raw_json": "not json {{"},
    )
    assert resp.status_code == 400
    assert (tmp_data_dir / "config.json").read_text() == original
```

- [ ] **Step 2: Run to verify fails**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py -v --no-cov -k "ratings or raw_json"`
Expected: 404s.

- [ ] **Step 3: Add the POST handlers**

Append to `flexlog/web/settings_bp.py`:

```python
def _parse_ratings_form() -> tuple[list[dict], list[str]]:
    """Read repeating rating_* form fields into a list of dicts. Returns
    (ratings_list, errors)."""
    ids = request.form.getlist("rating_id")
    labels = request.form.getlist("rating_label")
    descriptions = request.form.getlist("rating_description")
    scale_mins = request.form.getlist("rating_scale_min")
    scale_maxes = request.form.getlist("rating_scale_max")
    enabled_set = set(request.form.getlist("rating_enabled"))
    sortable_set = set(request.form.getlist("rating_sortable"))

    n = len(ids)
    if not (len(labels) == len(scale_mins) == len(scale_maxes) == n):
        return [], ["rating rows are misaligned; refresh the page and try again"]

    ratings: list[dict] = []
    errors: list[str] = []
    for i in range(n):
        rid = (ids[i] or "").strip()
        if not rid:
            continue
        try:
            smin = int(scale_mins[i])
            smax = int(scale_maxes[i])
        except (ValueError, TypeError):
            errors.append(f"ratings[{i}]: scale_min/scale_max must be integers")
            continue
        descr = (descriptions[i] if i < len(descriptions) else "") or None
        ratings.append({
            "id": rid,
            "label": (labels[i] or "").strip(),
            "description": descr if descr else None,
            "scale_min": smin,
            "scale_max": smax,
            "enabled": rid in enabled_set,
            "sortable": rid in sortable_set,
        })
    return ratings, errors


@settings_bp.post("/ratings")
def save_ratings():
    new_ratings, parse_errors = _parse_ratings_form()
    if parse_errors:
        return render_template(
            "settings/index.html",
            tab="ratings",
            config_dict=_config_as_dict(),
            errors=parse_errors,
            in_use_ids=_in_use_rating_ids(),
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400

    # Rename-protection: any id present in any session ratings_json must
    # appear in the new list (deletion is OK, rename to a different id is not).
    in_use = _in_use_rating_ids()
    new_ids = {r["id"] for r in new_ratings}
    lost = in_use - new_ids
    if lost:
        return render_template(
            "settings/index.html",
            tab="ratings",
            config_dict=_config_as_dict(),
            errors=[f"cannot rename or remove rating id {rid!r}: in use by existing sessions" for rid in lost],
            in_use_ids=in_use,
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400

    merged = _config_as_dict()
    merged["ratings"] = new_ratings
    result = _persist_and_swap(merged, errors_redir_tab="ratings")
    if result is not None:
        return result
    return redirect(url_for("settings.index", tab="ratings"), code=303)


@settings_bp.post("/raw")
def save_raw():
    raw = request.form.get("raw_json", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return render_template(
            "settings/index.html",
            tab="raw",
            config_dict=_config_as_dict(),
            errors=[f"JSON parse error at line {exc.lineno}, column {exc.colno}: {exc.msg}"],
            in_use_ids=_in_use_rating_ids(),
            raw_json=raw,
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400

    result = _persist_and_swap(parsed, errors_redir_tab="raw")
    if result is not None:
        return result
    return redirect(url_for("settings.index", tab="raw"), code=303)
```

Note: the rename-protection check is "lossy id detection" — if `in_use` IDs are missing from the new list, we reject regardless of whether the user intended rename or delete. This matches spec §4 ("Rename / change id: rejected with 422 if any session has that id"). For pure delete, the spec mandates "Sessions with that id retain the rating under 'Archived'" — but the simpler enforcement here ALWAYS blocks loss. To allow delete-while-archived, the user can disable the dimension instead (which keeps the id in config but with `enabled=false`). Document this in the UI message.

Actually re-reading the spec: "Delete: allowed. Sessions with that id retain the rating under 'Archived' on detail." So delete is allowed; only rename (i.e., the id changes shape but the dimension survives) is blocked. We need a way to distinguish "user deleted X and added Y" from "user renamed X to Y". The simplest distinction: if `len(new_ratings) == len(current)` AND every position is unchanged except one id, treat as rename. Otherwise it's add/remove.

Re-formulate: track row identity via a hidden `rating_original_id` field per row. The form sends the original id alongside the new id; if they differ AND the original is in_use, reject.

Update `_parse_ratings_form` to also read `rating_original_id` parallel list. Update `save_ratings`:

```python
def _parse_ratings_form() -> tuple[list[dict], list[tuple[str, str]], list[str]]:
    """Returns (new_ratings, [(original_id, new_id), ...], errors)."""
    ids = request.form.getlist("rating_id")
    original_ids = request.form.getlist("rating_original_id")
    # ... rest unchanged
    pairs: list[tuple[str, str]] = []
    for i in range(n):
        rid = (ids[i] or "").strip()
        orig = (original_ids[i] if i < len(original_ids) else "") or ""
        if rid:
            pairs.append((orig, rid))
    # ... existing parsing logic stays the same
    return ratings, pairs, errors
```

In `save_ratings`, replace the `lost = in_use - new_ids` block with:

```python
    new_ratings, id_pairs, parse_errors = _parse_ratings_form()
    if parse_errors:
        ... # unchanged
    in_use = _in_use_rating_ids()
    rename_violations = [
        (orig, new) for (orig, new) in id_pairs
        if orig and orig != new and orig in in_use
    ]
    if rename_violations:
        return render_template(
            "settings/index.html",
            tab="ratings",
            config_dict=_config_as_dict(),
            errors=[
                f"cannot rename {orig!r} → {new!r}: existing sessions reference {orig!r}"
                for orig, new in rename_violations
            ],
            in_use_ids=in_use,
            config_path=str(paths.config_path()),
            loaded_at=current_app.config.get("FLEXLOG_LOADED_AT"),
        ), 400
    # No further "lost ids" check: deletion is allowed; the dropped IDs
    # surface in the detail page as Archived.
```

Update the failing test `test_settings_ratings_rename_blocked_if_in_use` to send `rating_original_id=["energy"]` alongside `rating_id=["vigor"]` so the rename is detected:

```python
        "rating_original_id": ["energy"],
        "rating_id": ["vigor"],
```

- [ ] **Step 4: Implement the Ratings partial**

Replace `flexlog/templates/settings/_ratings.html`:

```html
<form method="post" action="{{ url_for('settings.save_ratings') }}" class="settings-form">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

  <p class="form-hint">Drag rows to reorder (JS not required — the order in the form is what persists). Disable a dimension to hide it from new sessions without losing existing scores.</p>

  <table class="ratings-table" data-ratings-table>
    <thead>
      <tr><th></th><th>id</th><th>Label</th><th>Description</th><th>min</th><th>max</th><th>Enabled</th><th>Sortable</th><th></th></tr>
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
        <td><input type="number" name="rating_scale_min" value="{{ r.scale_min }}" min="0" max="99" required></td>
        <td><input type="number" name="rating_scale_max" value="{{ r.scale_max }}" min="1" max="100" required></td>
        <td><input type="checkbox" name="rating_enabled" value="{{ r.id }}" {% if r.enabled %}checked{% endif %}></td>
        <td><input type="checkbox" name="rating_sortable" value="{{ r.id }}" {% if r.sortable %}checked{% endif %}></td>
        <td><button type="button" class="btn rating-delete" data-rating-delete>✕</button></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <button type="button" class="btn" data-rating-add>+ Add rating dimension</button>

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
    <td><input type="number" name="rating_scale_min" value="0" min="0" max="99" required></td>
    <td><input type="number" name="rating_scale_max" value="5" min="1" max="100" required></td>
    <td><input type="checkbox" name="rating_enabled" checked></td>
    <td><input type="checkbox" name="rating_sortable" checked></td>
    <td><button type="button" class="btn rating-delete" data-rating-delete>✕</button></td>
  </tr>
</template>
```

The "Sortable" checkbox value attribute on the template needs to dynamically bind to the id; settings.js (Task 16) handles that on row creation.

- [ ] **Step 5: Implement the Raw JSON partial**

Replace `flexlog/templates/settings/_raw.html`:

```html
<form method="post" action="{{ url_for('settings.save_raw') }}" class="settings-form">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <p class="form-hint">Edit the entire config.json. Saves only if the JSON parses AND passes validation. Existing tab edits are discarded.</p>
  <textarea name="raw_json" class="raw-json-editor" rows="24" spellcheck="false">{{ raw_json or (config_dict | tojson(indent=2)) }}</textarea>
  <div class="form-actions">
    <button type="submit" class="btn btn-primary">Save</button>
  </div>
</form>
```

- [ ] **Step 6: Run tests + full suite**

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py -v --no-cov`
Expected: all PASS.

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 7: Commit**

```bash
git add flexlog/web/settings_bp.py flexlog/templates/settings/_ratings.html flexlog/templates/settings/_raw.html tests/integration/test_settings_routes.py
git commit -m "settings: Ratings + Raw JSON tabs

Ratings tab edits the rating-dimension list as repeating rows
(id, label, description, scale_min/max, enabled, sortable). A
hidden rating_original_id per row catches rename attempts on
ids that are in use; rename-while-in-use is rejected with a
422-style validation error so existing session data stays
referenceable.

Raw JSON tab posts the entire config as one textarea; parse
errors surface with line/column, validation errors with field
paths. Both flow through validate_config_dict + atomic write."
```

---

## Task 16: `settings.js` — drag-reorder, inline add/delete, checkbox value binding

Client behavior for the Ratings tab: drag-to-reorder rows, "+ Add rating dimension" clones the `<template>`, ✕ deletes a row, and the `rating_sortable`/`rating_enabled` checkbox `value` attributes sync to the id input (so `getlist("rating_sortable")` returns the right ids).

**Files:**
- Create: `flexlog/static/js/settings.js`

- [ ] **Step 1: Implement**

Create `flexlog/static/js/settings.js`:

```javascript
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  bindRatingsTable();
});

function bindRatingsTable() {
  const tbody = document.querySelector("[data-ratings-tbody]");
  if (!tbody) return;
  const addBtn = document.querySelector("[data-rating-add]");
  const tmpl = document.getElementById("rating-row-template");

  const syncCheckboxValues = (row) => {
    const idInput = row.querySelector('input[name="rating_id"]');
    const enabled = row.querySelector('input[name="rating_enabled"]');
    const sortable = row.querySelector('input[name="rating_sortable"]');
    const sync = () => {
      enabled.value = idInput.value;
      sortable.value = idInput.value;
    };
    idInput.addEventListener("input", sync);
    sync();
  };
  tbody.querySelectorAll(".rating-row").forEach(syncCheckboxValues);

  addBtn?.addEventListener("click", () => {
    const clone = tmpl.content.cloneNode(true);
    const row = clone.querySelector(".rating-row");
    tbody.appendChild(clone);
    syncCheckboxValues(row);
    row.querySelector('input[name="rating_id"]').focus();
  });

  tbody.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-rating-delete]");
    if (btn) btn.closest(".rating-row").remove();
  });

  let dragged = null;
  tbody.addEventListener("dragstart", (e) => {
    const row = e.target.closest(".rating-row");
    if (!row) return;
    dragged = row;
    row.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  tbody.addEventListener("dragend", () => {
    if (dragged) dragged.classList.remove("dragging");
    dragged = null;
  });
  tbody.addEventListener("dragover", (e) => {
    e.preventDefault();
    const target = e.target.closest(".rating-row");
    if (!target || target === dragged) return;
    const rect = target.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    tbody.insertBefore(dragged, before ? target : target.nextSibling);
  });
}
```

- [ ] **Step 2: Smoke test the file is served**

Append to `tests/integration/test_settings_routes.py`:

```python
def test_settings_js_served(authed_client):
    resp = authed_client.get("/static/js/settings.js")
    assert resp.status_code == 200
    assert b"bindRatingsTable" in resp.data
```

Run: `.venv/bin/python -m pytest tests/integration/test_settings_routes.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 3: Manual browser smoke**

```bash
make dev
```

Visit `/settings?tab=ratings` — click "+ Add rating dimension", row appears with focus on the id input. Drag rows to reorder. ✕ removes a row. Save; order in `config.json` matches the visible order.

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 5: Commit**

```bash
git add flexlog/static/js/settings.js tests/integration/test_settings_routes.py
git commit -m "settings.js: drag-reorder, add/delete rows, value sync

Drag-and-drop reordering via HTML5 DnD (no library). The
'Sortable' and 'Enabled' checkbox value attrs auto-sync to the
id input so getlist('rating_sortable') returns ids."
```

---

## Task 17: Sweep stragglers + CSS polish

Catch any stale reference to v1 schema fields (`overall_score`, `custom_ratings_json`) or v1 form shape (`link_url[]`/`link_label[]`). Add CSS for the new UI components.

**Files:**
- Modify: `flexlog/static/css/main.css`, any test still using v1 shape

- [ ] **Step 1: Search for stragglers**

Run:

```bash
grep -rn "overall_score\|custom_ratings_json" flexlog/ tests/ | grep -v ".pyc"
grep -rn 'name="link_url"\|name="link_label"' flexlog/ tests/
```

Fix each match. Where a test's intent was the old shape, either delete (if covered elsewhere) or rewrite for the new shape.

- [ ] **Step 2: Append CSS**

Append to `flexlog/static/css/main.css`:

```css
/* Settings tabs */
.settings-tabs { display: flex; gap: 0; border-bottom: 1px solid #d1d5db; margin-bottom: 1rem; }
.settings-tabs a { padding: 0.6rem 1rem; color: #4b5563; text-decoration: none; border-bottom: 2px solid transparent; }
.settings-tabs a.active { color: #111; border-bottom-color: #2563eb; font-weight: 600; }

.settings-errors { padding: 0.8rem 1rem; background: #fee2e2; border-left: 3px solid #dc2626; margin-bottom: 1rem; }
.settings-errors ul { margin: 0.4rem 0 0 1.2rem; }

.ratings-table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
.ratings-table th, .ratings-table td { padding: 0.4rem 0.5rem; border-bottom: 1px solid #e5e7eb; vertical-align: middle; }
.ratings-table input[type="text"], .ratings-table input[type="number"] { width: 100%; box-sizing: border-box; }
.rating-row.dragging { opacity: 0.5; }
.rating-row .drag-handle { cursor: grab; color: #9ca3af; user-select: none; }
.ui-strings-table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
.ui-strings-table input { width: 100%; box-sizing: border-box; }
.raw-json-editor { width: 100%; font-family: ui-monospace, SFMono-Regular, monospace; font-size: 12px; }

/* Pending-uploads list */
.pending-list { list-style: none; margin: 0 0 0.4rem 0; padding: 0; }
.upload-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.4rem 0.6rem; border-radius: 4px; margin-bottom: 0.2rem; background: #f9fafb; }
.upload-row[data-status="uploaded"] { background: #f0fdf4; }
.upload-row[data-status="uploading"] { background: #fef3c7; }
.upload-row[data-status="failed"] { background: #fee2e2; }
.upload-row .upload-name { flex: 1; font-size: 13px; }
.upload-row .upload-status { font-size: 12px; color: #4b5563; }
.upload-row progress { width: 100px; height: 8px; }
.upload-row .upload-remove { font-size: 11px; padding: 2px 8px; }

/* Link section */
.link-list { list-style: none; padding: 0; margin: 0 0 0.6rem 0; }
.link-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.4rem 0.6rem; background: #f0f9ff; border-radius: 4px; margin-bottom: 0.2rem; }
.link-row a { flex: 1; }
.link-add-row { display: flex; gap: 0.4rem; }
.link-add-row input[type="url"] { flex: 1; }
.link-add-error { color: #dc2626; font-size: 12px; margin: 0.2rem 0 0 0; }
```

- [ ] **Step 3: Run full suite + coverage**

Run: `.venv/bin/python -m pytest 2>&1 | tail -10`
Expected: green, ≥85% total coverage.

- [ ] **Step 4: Manual full-flow smoke**

```bash
make dev
```

End-to-end walk:

1. Log in.
2. `/settings` — five tabs render. Edit App name → save → refresh → sticks. Edit a UI string → observe on `/`.
3. Add a rating dimension via Ratings tab → save → `/people/<id>/sessions/new` shows the new `rating_<id>` input.
4. Create a session: progressive upload of 2 photos, remove one, add 1 link, save. Detail page shows photo + link in the new order.
5. Edit the session: remove the photo via ✕, add an audio file, save. Detail reflects change. No audio download anchor.
6. Ratings tab: attempt to rename the dim used by the saved session → error.
7. Raw JSON tab: invalid JSON → error with line/col → `config.json` untouched.

- [ ] **Step 5: Commit**

```bash
git add flexlog/static/css/main.css tests/
git commit -m "polish: CSS for new UI + sweep stragglers

Adds styles for pending-uploads rows (status colors, progress),
settings tabs, ratings table, raw JSON editor, link list.
Sweeps any remaining test that still references the v1 schema
shape or v1 form shape."
```

---

## Task 18: Version bump to v0.3.0 + README

Final commit — record the milestone.

**Files:**
- Modify: `pyproject.toml`, `README.md`

- [ ] **Step 1: Bump version**

In `pyproject.toml`:

```toml
version = "0.3.0"
```

- [ ] **Step 2: Update README**

Add to `README.md` near the changelog / roadmap area:

```markdown
## v0.3.0 — Settings UI + session-form UX overhaul

- **Settings page** at `/settings` — five tabs (App, Ratings, UI strings, Limits, Raw JSON) replace hand-editing `config.json`.
- **Custom rating fields** — the hardcoded `overall_score` is gone. All rating dimensions are defined in config (add / rename / disable / delete / reorder). Existing data is migrated automatically on first launch.
- **Progressive media uploads** — photos / audio / video upload immediately when added, with per-file progress and remove. Save is a fast link-only operation.
- **Revamped links UI** — single URL textbox + Add. Validated client-side and server-side.
- **Session detail reorder** — Links → Ratings → Notes → Audio → Photos → Videos. Audio plays inline; the redundant Download anchor is removed.

**Migration:** runs automatically on first startup via `PRAGMA user_version`. The previous `overall_score` column is merged into a unified `ratings_json` keyed by config dimension id. No data wipe; backups remain wise before any upgrade.
```

- [ ] **Step 3: Run final suite**

Run: `.venv/bin/python -m pytest 2>&1 | tail -3`
Expected: green, ≥85%.

- [ ] **Step 4: Commit + tag**

```bash
git add pyproject.toml README.md
git commit -m "v0.3.0: settings UI + session-form UX overhaul

See README for the full change list. Migration auto-runs on
first startup; existing session data is preserved with the
old overall_score column merged into ratings_json under the
stable id 'overall_score'."
git tag v0.3.0
```

Do NOT push the tag — leave that to the user.

---

## Self-Review

**Spec coverage (each spec section → task[s] that implement it):**

- §1 (goals 1–5) — Tasks 5–12 (ratings + settings + upload + links + detail).
- §2 (schema + migration) — Tasks 3, 4, 5.
- §3 (config schema v2) — Tasks 1, 2.
- §4 (settings page + routes) — Tasks 13, 14, 15, 16.
- §5 (async upload + endpoints + service layer + JS + beforeunload + edit mode) — Tasks 7, 8, 9, 10, 11.
- §6 (links revamp) — Tasks 5 (server parse), 10 (template), 11 (JS).
- §7 (detail reorder + audio polish) — Task 12.
- §8 (error handling) — distributed across Tasks 8, 11, 13–15 (each handler's failure path).
- §9 (testing strategy) — every task ships its own unit/integration tests; Task 17 sweeps the rest.
- §10 (rollout) — Task 18.
- §11 (files touched) — matches the file map at the top of this plan.

No gaps.

**Placeholder scan:** scanned for "TBD"/"TODO"/"similar to"/"add appropriate error handling" — none.

**Type consistency:** rating dict shape is `{id: int}` everywhere (`_serialize_ratings`, `split_ratings`). Function signatures for `create_session`/`update_session` match between Task 5 and Tasks 9/10 (kwargs `ratings: dict[str, int]`, `link_urls: list[str]`). `file_keys_by_kind: dict[str, list[str]]` shape matches between Task 7 (service) and Tasks 9/10 (route handler + template). Hidden input names match across template (`photo_keys`/`audio_keys`/`video_keys`/`link_urls`/`unlinked_keys`) and `request.form.getlist(...)` calls. CSRF token retrieval matches between Tasks 8/9 (JS reads `<meta name="csrf-token">`; server reads `X-CSRFToken` header — Flask-WTF default).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-10-flexlog-m6-session-ux-settings-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?





