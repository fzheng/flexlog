# flexlog — Runtime Config Reload — Design

**Status:** Approved 2026-05-09 (post-MVP, first item after `m5-mvp` tag).

**Goal:** Let the owner edit `config.json` while the app is running and see the changes (UI strings, entity labels, rating dimensions, upload limits) take effect on the next request — without restarting the process.

**Non-goals:**
- In-app editing of `config.json` (the owner edits the file externally).
- Reloading the secret key or DB schema.
- Multi-process safe reload (PRD is single-user local-only — one process, one config).

## Context

PRD §13.3 set the MVP default as "configuration changes apply only at app restart" — a deliberate scope cut. Now that the MVP has shipped (tag `m5-mvp`), this design lifts that restriction.

The `Config` dataclass loads once in `flexlog/app.py:create_app()` via `flexlog/config_loader.py:load_or_bootstrap` and lives in `app.config["FLEXLOG"]`. Every label render reads it through the `ui` Jinja filter or `build_labels_context` (`flexlog/web/filters.py`). Rating dimensions for the dashboard sort and session form come from `flexlog/services/sessions.py:enabled_rating_dimensions()`, which also reads `current_app.config["FLEXLOG"]`. Upload size limits come from `Config.limits` and are read per-upload in `flexlog/services/media.py`.

This means a single `app.config["FLEXLOG"] = new_config` assignment makes every subsequent render and upload see the new values — no restarts, no template recompilation, no DB migration.

## Trigger

A two-route blueprint:

| Route | Method | Purpose |
|---|---|---|
| `/settings` | GET | Renders the settings page: config file path, `FLEXLOG_LOADED_AT` timestamp, a "Reload now" button (CSRF-protected POST). |
| `/settings/reload` | POST | Calls `load_or_bootstrap(paths.config_path())`. On success swaps `app.config["FLEXLOG"]` + updates `FLEXLOG_LOADED_AT`. On failure leaves old config in place. Flashes the result. Redirects (303) to `/settings`. |

No auth beyond CSRF (single-user local-only per PRD).

## Architecture

### New files

- `flexlog/web/settings_bp.py` — blueprint with the two routes.
- `flexlog/templates/settings/index.html` — page template (path, timestamp, button, flash area).
- `tests/integration/test_settings.py` — 4 integration tests.

### Modified files

- `flexlog/web/__init__.py` — register `settings_bp`.
- `flexlog/templates/_base.html` — add Settings nav link; add flash-message rendering block (currently absent — adding it is a side-benefit for any future flashes).
- `flexlog/app.py` — set `app.config["FLEXLOG_LOADED_AT"] = datetime.now(timezone.utc)` after the initial config load.
- `flexlog/web/filters.py` — extend `BUILTIN_UI_DEFAULTS` with 6 keys: `settings`, `reload_config`, `config_path_label`, `config_loaded_at_label`, `config_reload_failed`, `config_reload_succeeded`.

### Atomic swap

`app.config` is a `dict`-like mapping. Single key writes are atomic under the CPython GIL. The reload route assigns the freshly-built `Config` object only after `load_or_bootstrap` returns successfully, so a partial / corrupt config can never be visible. If validation raises, the existing object is untouched.

```python
@settings_bp.post("/settings/reload")
def reload_config():
    try:
        new_cfg = load_or_bootstrap(paths.config_path())
    except ConfigError as e:
        flash(f"{ui_filter('config_reload_failed')}: {e}", "error")
        return redirect(url_for("settings.index"), code=303)
    current_app.config["FLEXLOG"] = new_cfg
    current_app.config["FLEXLOG_LOADED_AT"] = datetime.now(timezone.utc)
    flash(ui_filter("config_reload_succeeded"), "success")
    return redirect(url_for("settings.index"), code=303)
```

(Sketch — exact code lives in the implementation plan.)

### Flash messages

`_base.html` currently has no flash-rendering block. The settings work depends on flashes for error feedback, so the layout gets a small addition:

```jinja
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <ul class="flash-messages">
      {% for category, message in messages %}
        <li class="flash flash-{{ category }}">{{ message }}</li>
      {% endfor %}
    </ul>
  {% endif %}
{% endwith %}
```

Plus a few CSS rules for `.flash`, `.flash-success`, `.flash-error`. This becomes available app-wide — `people_bp.destroy` already calls `flash(...)` (M2 code) but the messages have never been rendered. This change closes that latent gap.

## Behaviour contract

1. **Happy path:** owner edits `config.json` → POSTs `/settings/reload` → next GET on any page shows the new labels / new rating dimensions / new entity strings.
2. **Error path:** invalid JSON / failed validation → flash the validator's error string → old config remains active.
3. **Page contents:** `/settings` shows
   - the absolute path to `config.json` (`paths.config_path()`)
   - the loaded-at timestamp (`FLEXLOG_LOADED_AT`)
   - a "Reload now" submit button
   - any pending flash messages

The reload affects subsequent requests, not the response that triggered the reload (the redirect target is the next request). This matches Flask's natural request lifecycle.

## Tests

Four integration tests in `tests/integration/test_settings.py`:

1. **`test_settings_page_renders`** — GET returns 200, body contains the config path string and a `<form>` posting to `/settings/reload`.
2. **`test_reload_picks_up_new_label`** — write a `ui_strings` override into the test data dir's `config.json`, POST `/settings/reload`, GET `/`, assert the new label appears.
3. **`test_reload_with_invalid_json_keeps_old_config`** — overwrite `config.json` with malformed bytes, POST reload, assert the response (after redirect) contains a flash error AND the old label is still active on `/`.
4. **`test_reload_post_requires_csrf`** — POST `/settings/reload` without the CSRF token returns 400.

A unit-level CSS regression test that the new `.flash-*` rules render is unnecessary (covered transitively by test 3 — the flash must be visible to the assertion).

## Risk and rollback

**Risk:** very low. The reload path is read-only of disk, write-only of in-memory state, and gated by the existing validator that the startup path already trusts. If the swap fails, the old config persists. The single-process assumption (PRD §13.5: single-user local-only) means there's no cross-process synchronization to get wrong.

**Rollback:** `git revert` the implementation commit. No data changes, no schema changes.

## Out of scope

- In-app config editor (would require an atomic file write + validation UX, materially bigger).
- Multi-process / production-WSGI reload (each process would need its own reload — not a single-user concern).
- File watcher / auto-reload (adds a thread + dependency for marginal gain over an explicit button).
- Signal handlers (SIGHUP) — covered by the button; would re-add value only in a headless deployment.

If those are wanted later, they layer onto this design without rework.

## Estimated diff

≈150 lines across 6 source files + 1 test file. Single commit. One-day implementation including tests + browser smoke.

---

**End of design.**
