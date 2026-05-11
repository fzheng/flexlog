# M6 — Settings UI + Session-form UX overhaul

**Status:** Design (draft, awaiting user review)
**Date:** 2026-05-10
**Version target:** v0.3.0
**Branches affected:** main

---

## 1. Goal

Ship five user-facing enhancements as one milestone:

1. Custom rating fields fully replace the hardcoded `overall_score`. Ratings become entirely config-driven (add/rename/disable/reorder/delete).
2. A `/settings` page lets the user edit `config.json` from the UI (all four sections + a Raw JSON tab) instead of hand-editing the file.
3. Photo / audio / video uploads happen progressively in the session form — each file uploads on Add, appears in a removable list, with Save reduced to a fast "link" operation.
4. The links section becomes one URL textbox + Add button, with the running list rendered above (delete-per-item).
5. The session-detail page reorders to: Links → Ratings → Notes → Audio → Photos → Videos, and the audio "Download" anchor is removed.

The avatar cropper, dashboard sort *logic* (already exists, just adapts), and non-session UI are out of scope.

## 2. Schema changes (DB)

**Drop:** `Session.overall_score` column (was `INT NOT NULL CHECK (0..5)`).

**Rename:** `Session.custom_ratings_json` → `Session.ratings_json`. Same `TEXT` type. Now holds the *only* rating store — JSON like `{"energy": 4, "clarity": 5}` keyed by config rating `id`.

**No other column changes.** `SessionLink.label` stays in the schema (existing rows preserved) but the new form drops the label input.

### Migration

Schema version is tracked via SQLite's built-in `PRAGMA user_version` (no new table needed). On app startup, after `attach_engine_at_runtime`, run an idempotent migration:

1. Read current schema version. If ≥ 2, skip.
2. Open a transaction (SAVEPOINT for safety).
3. For each `Session` row:
   - Parse `custom_ratings_json` (default `{}`).
   - If `overall_score` is present, write it into the dict under the id `"overall_score"` (a stable, recognizable key — the migration does NOT try to remap to whatever dimension is currently first in config, because config can be edited freely; `"overall_score"` becomes an archived id if the user removes that dimension).
   - Write the merged dict to the new `ratings_json` column.
4. `ALTER TABLE session DROP COLUMN overall_score`.
5. Bump schema version to 2.
6. Commit.

Reruns are no-ops (the version gate catches it). Migration failure aborts startup with a logged stack trace and a friendly error page — no partial writes.

## 3. Config schema (`config.json`)

```json
{
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
```

### New / changed validation rules

- `schema_version`: required int. Code-bumped only; never edited by hand.
- `ratings[].id`: snake_case, `^[a-z][a-z0-9_]{0,31}$`, unique within the array. **Immutable once any session references that id** — the settings UI greys out the field on edit. (Server enforcement: settings save rejects renames if a session row has the old id in `ratings_json`.)
- `ratings[].scale_min` < `ratings[].scale_max`, both ints in 0..100.
- `ratings[].sortable`: bool, default true on add. Drives whether the dashboard sort dropdown lists this dimension.
- `ratings` array order = display order on the form, on the detail page, and in the dashboard sort dropdown.
- Default bootstrap config: one example dimension (`energy`, 0–5, enabled, sortable). Old defaults (`overall_quality`, `clarity`) are removed from the bootstrap JSON.

### Archived ratings

If a session has a rating for an id that's been deleted or disabled in the current config, the detail page shows it under "Archived ratings" (existing behavior, kept verbatim). Re-adding a dimension with the same id restores it to "current".

## 4. Settings page

**Routes** (all authed + CSRF-protected, declared in `flexlog/web/settings_bp.py`):

- `GET /settings` — render the page; tab selection via `?tab=app|ratings|ui_strings|limits|raw`, default `app`.
- `POST /settings/<section>` — save one tab; sections `app`, `ratings`, `ui_strings`, `limits`.
- `POST /settings/raw` — save raw JSON (whole-config replace).

**Templates:**

- `flexlog/templates/settings/index.html` — base page with horizontal tab nav.
- `flexlog/templates/settings/_app.html`, `_ratings.html`, `_ui_strings.html`, `_limits.html`, `_raw.html` — one partial per tab.

**JS:** `flexlog/static/js/settings.js` handles client-side tab switching (history.replaceState on `?tab=`), drag-reorder on the ratings list (HTML5 DnD, no library), and the "Add rating dimension" / "Delete" inline interactions.

**Save pipeline (POST `/settings/<section>`):**

1. Read current loaded config (`current_app.config["FLEXLOG"]`).
2. Build a new full dict by merging the submitted tab's fields over the current config dict.
3. Run the merged dict through `validate_config_dict(d) -> tuple[Config | None, list[str]]`, a new public function in `flexlog/config_loader.py` that is the dict-to-Config validation path currently inlined in `load_config`. `load_config` is refactored to call it (`load_config` becomes "read file → parse JSON → `validate_config_dict`").
4. If invalid: re-render the active tab with field-level errors. No disk write.
5. If valid: atomic write to `config.json` (write `.tmp.<random>` with mode 0600, fsync, rename — mirroring `flexlog/kdf_params.py:write_kdf_params`). Then `current_app.config["FLEXLOG"]` is replaced with the new `Config` so changes take effect on the next request.

**POST `/settings/raw`:** identical pipeline but the input is `json.loads(textarea_body)`. Parse errors render with line/column. Validation errors render with field paths.

**Rating-dimension edits — server enforcement:**

- Rename / change `id`: rejected with 422 if any session has that id in `ratings_json`. Settings UI also disables the id field client-side for this case (the page payload includes the set of "in-use" ids).
- Delete: allowed. Sessions with that id retain the rating under "Archived" on detail.
- Disable (`enabled: false`): allowed. Same effect as delete for runtime UI, but the dimension is preserved in config so it can be re-enabled.

## 5. Async upload flow

### New endpoints

- `POST /sessions/upload` — multipart body with one `file` field and a `kind` form field (`photo|audio|video`). Authed + CSRF-protected. Routes through the existing `flexlog/services/media.py:upload_to_media_file` (dedup, MIME magic-byte check, chunked AES-GCM encrypt). Enforces the per-kind file-count and size caps from `Config.limits`. Returns JSON:

  ```json
  { "file_key": "abc123...", "original_filename": "photo.jpg",
    "media_type": "photo", "size_bytes": 2185000, "mime": "image/jpeg" }
  ```

  Errors: 413 (oversized), 415 (bad MIME), 422 (cap exceeded), JSON body `{ "error": "<message>" }`.

- `DELETE /sessions/upload/<file_key>` — best-effort orphan delete. Server queries: any `SessionMedia` row OR any `Person.avatar_media_id` referencing this key? If none, deletes the encrypted file from disk + the `MediaFile` row. If yes (dedup hit), leaves it alone. Always returns 204. Authed + CSRF-protected.

### CSRF for AJAX

The session form renders a `<meta name="csrf-token" content="...">` tag. `session_form.js` reads it once and sets `X-CSRFToken` on every XHR. Flask-WTF's CSRFProtect accepts that header by default.

### Client-side state (`flexlog/static/js/session_form.js`)

Three pending lists keyed by media kind:

```js
{ photos: [{ file_key, original_filename, size_bytes, status }, ...],
  audios: [...],
  videos: [...] }
```

`status` is one of `uploading | uploaded | failed`.

Each kind's `<fieldset>` renders the pending list above a "+ Add" button. Each row shows filename, size, status indicator, and a ✕ button. Uploading rows show a progress bar driven by `XMLHttpRequest.upload.onprogress` (fetch can't expose upload progress).

On form submit:

- If any item is in `uploading` status, the submit is blocked with an inline banner ("Wait for uploads to finish") — no queuing.
- Otherwise, the form submits with three hidden input arrays (`photo_keys[]`, `audio_keys[]`, `video_keys[]`) carrying the `file_key`s of all `uploaded` items in order.

### Edit-mode behavior

Existing `SessionMedia` rows render the same list pattern, pre-populated, with a `data-existing="true"` marker. Removing an existing row sets a hidden `unlinked_keys[]` array; the server unlinks those alongside the new links on save. The current checkbox-based "Remove" UI is replaced.

### beforeunload

`window.addEventListener('beforeunload', ...)` fires the browser's "unsaved changes" prompt **only** when the pending list contains uploaded-but-unlinked files AND the form hasn't been submitted yet. Pure-text edits (notes, ratings) don't trigger an override — browsers handle that themselves.

### Service-layer changes

`flexlog/services/sessions.py`:

- New: `link_media_to_session(db, session_id, file_keys_by_kind)` — for each (`kind`, `file_key`), create a `SessionMedia` row.
- New: `unlink_media_from_session(db, session_id, file_keys)` — remove `SessionMedia` rows by `(session_id, file_key)`.
- Removed (or simplified) from `create_session` / `update_session`: the multipart-decoding + immediate-upload path. Those handlers now just receive the `[photo|audio|video]_keys[]` arrays and call `link_media_to_session`.

## 6. Links revamp

**Form:** one `<input type="url" name="new_link_url">` + an `Add` button. Pressing Enter == clicking Add. On Add, client-side validates the URL parses and has a scheme + host. If valid: appends to a list above the input; clears the input. The list shows each URL as a clickable anchor with a ✕ button.

**State:** a hidden `<input name="link_urls[]">` array carries the ordered list to the server on form submit. Server validates again (using whatever URL validator exists in `services/sessions.py`).

**Schema:** `SessionLink(url, label, order)` rows stay as-is. The `label` column is preserved for existing data (older rows still show their label on the detail page) but the new form doesn't set labels. No migration to drop the column — keeping it costs nothing and avoids needless schema churn.

**JS:** lives in `flexlog/static/js/session_form.js` (same file as the upload flow, since both manage the form state).

## 7. Detail page

**New section order (top to bottom):**

1. Header (breadcrumb to person, session date, edit button)
2. **Links**
3. **Ratings** (the custom-rating list, in `ratings` config order; no separate "Overall Score" line)
4. **Notes**
5. **Audio**
6. **Photos**
7. **Videos**

Empty sections collapse — no "no audio" placeholder unless the section is structurally always-shown (Links and Ratings are always rendered; Notes only when non-empty; media only when present).

**Audio template change:** `flexlog/templates/_partials/media_audio.html` drops the `<a class="audio-download">` anchor. The corresponding `.audio-download` CSS rule in `flexlog/static/css/main.css` is removed.

## 8. Error handling

- **Upload endpoint 4xx:** JSON `{error: <message>}`. JS marks the row `failed`, shows the message inline with a Retry button. The row only appears in the pending list once the upload at least starts (file selected → row appended → XHR fires).
- **Upload network failure:** XHR `error`/`abort` events → same `failed` treatment.
- **Save with stale `file_key`** (file was orphan-deleted between upload and Save — uncommon but possible if the user opens two tabs): server returns 422 with the offending key list. Form re-renders with those rows marked invalid; user removes them and re-saves.
- **Settings save invalid:** re-render active tab with field-level errors. `config.json` is never touched until validation passes.
- **Migration failure on startup:** abort startup with a logged stack trace. The user sees a friendly setup-error page explaining the migration failed and pointing at the log file. Each migration step wraps in a SAVEPOINT, rolled back on exception, so the DB is never half-migrated.
- **Settings rename conflict** (id change with existing session references): 422 with field error "in use — cannot rename".

## 9. Testing strategy

Coverage floor stays at 85% (enforced by `pyproject.toml --cov-fail-under=85`). The existing 561 tests adapt:

- Wherever a test references `overall_score` (the column), it switches to the equivalent `ratings_json["overall_score"]` access.
- Tests that POST sessions with `overall_score=<n>` move to posting `rating_overall_score=<n>` (the form input naming convention is `rating_<id>` for every dimension; the legacy `overall_score` becomes one more `rating_<id>` row, except the bootstrap default config no longer enables an `overall_score` dimension, so test fixtures must either configure their own dimension or use the new bootstrap default `energy`).

### New unit tests

- `tests/unit/test_config_schema_v2.py`: validates the new fields (sortable, schema_version, id immutability, scale bounds), validation error messages, default-bootstrap config.
- `tests/unit/test_settings_service.py`: the `validate_config_dict` extraction; merge behavior for partial-section saves.
- `tests/unit/test_migrations.py`: a v1-schema DB → migrate → check `ratings_json` content; second run is a no-op; corrupted `custom_ratings_json` falls back to `{}`.

### New integration tests

- `tests/integration/test_settings_routes.py`: all four section saves + raw JSON; CSRF rejection; validation rejection re-renders the active tab; rename-rejection on in-use id; orphan archived-ratings preserved after a delete.
- `tests/integration/test_session_async_upload.py`: POST upload → DELETE orphan path (no other refs) → DELETE non-orphan path (dedup hit) → POST upload + save with `photo_keys[]` → SessionMedia row created; stale key on save returns 422.
- `tests/integration/test_session_form_e2e.py`: full create flow via test client — upload 2 photos, remove 1, add 1 link, save → assert session has 1 photo + 1 link.
- `tests/integration/test_detail_order.py`: a fully-populated session renders sections in the new order; audio template has no download link.

## 10. Rollout

- Ships as **v0.3.0**. Bump `pyproject.toml` version.
- README updates: document the auto-migration (no data wipe, idempotent), the new `/settings` page, and the new upload flow.
- No flag-gating — the new UI replaces the old in one commit per task.

## 11. Files touched (summary)

**Modified:**

- `flexlog/db/models.py` — drop `overall_score`; rename `custom_ratings_json` → `ratings_json`. (No new table — version tracking uses `PRAGMA user_version`.)
- `flexlog/config_loader.py` — `schema_version`, `sortable`, new validation, new default bootstrap JSON, `validate_config_dict` extraction.
- `flexlog/services/sessions.py` — `enabled_rating_dimensions` stays; new `link_media_to_session`, `unlink_media_from_session`; `create_session`/`update_session` lose multipart handling.
- `flexlog/services/people.py:list_dashboard_rows` — sort options now derived from `ratings[].sortable`.
- `flexlog/web/sessions_bp.py` — handlers slim down; upload-handling moves out.
- `flexlog/web/dashboard_bp.py` — sort options derive from config.
- `flexlog/web/settings_bp.py` — full new implementation (currently a stub).
- `flexlog/templates/sessions/_form_body.html` — new pending-uploads UI + new links UI; "Overall Score" input gone.
- `flexlog/templates/sessions/detail.html` — section reorder.
- `flexlog/templates/_partials/media_audio.html` — drop download anchor.
- `flexlog/static/css/main.css` — drop `.audio-download`; add styles for pending-uploads list + settings tabs.

**New:**

- `flexlog/migrations/v1_to_v2.py` — the migration script (idempotent).
- `flexlog/web/upload_bp.py` — the two new AJAX endpoints (`POST /sessions/upload`, `DELETE /sessions/upload/<file_key>`).
- `flexlog/templates/settings/index.html` + five partials.
- `flexlog/static/js/settings.js`.
- `flexlog/static/js/session_form.js`.

**Deleted:** none (we preserve `SessionLink.label`).

## 12. Open questions

None remaining. All design decisions are pinned.
