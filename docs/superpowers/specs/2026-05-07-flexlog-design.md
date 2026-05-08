# flexlog — System Design (MVP)

**Date:** 2026-05-07
**Status:** Approved (high-level architecture)
**Source PRD:** `docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md` (v3, May 2026)
**Cycle shape:** This is the high-level architecture spec covering the whole MVP. Each milestone (M1–M5, see §11) gets its own sub-spec → plan → implementation cycle.

---

## 1. Summary

flexlog is a local-only, single-user web app for recording recurring 1v1 sessions with people. Structured data lives in one SQLite file under a user-supplied `FLEXLOG_DATA_DIR`; media files live in `uploads/` under that same directory using **content-addressed storage** with **SHA-256 dedup**. All user-facing labels come from `config.json` so the same codebase re-themes for interview logs, coaching journals, language exchange logs, etc.

This spec deviates from PRD §6.3's per-session disk hierarchy in favor of content-addressed sharded storage, and replaces PRD §6.10's hard-cascade delete model with a **soft-unlink + Media Library hard-delete** model. Both deviations are decisions taken during design; rationale is in §4 and §5.

## 2. Locked decisions

| | Decision |
|---|---|
| Stack | Python 3.11+, Flask 3.x, Jinja2, SQLAlchemy 2.x ORM, Flask-WTF, pytest |
| DB | Single SQLite file at `$FLEXLOG_DATA_DIR/data/encounters.db`. Default rollback-journal mode. |
| Migrations | None. `Base.metadata.create_all()` at startup. Single user, no scale concerns. |
| IDs | UUID strings (PRD §13.4). |
| Media storage | Content-addressed: `uploads/<sha[0:2]>/<sha[2:4]>/<sha>.<ext>`. SHA-256 dedup on upload. |
| Retention | Soft-unlink from people/sessions; files persist on disk. Hard delete only via Media Library. |
| Frontend | Server-rendered Jinja + vendored JS libs (Cropper.js, PhotoSwipe) + vanilla page modules. No bundler. |
| Bind | `127.0.0.1`, port from `FLEXLOG_PORT` (default 5050). Debug off by default. |
| Run | `pip install -e .`, then `flexlog` (console script) or `python -m flexlog`. |
| Test gate | pytest with `--cov=flexlog --cov-fail-under=85`. |

PM defaults from PRD §13 are accepted as-is: `overall_score` required; deletes are permanent after confirmation (now: hard-delete from Media Library only); config changes apply on restart; UUIDs; rollback-journal mode.

## 3. Architecture

### 3.1 Stack & request lifecycle

Python 3.11+, Flask 3.x with the application factory pattern. Routes are organized into feature blueprints. Each request: blueprint route → Flask-WTF form/CSRF validation → service-layer call (which uses SQLAlchemy session + the storage service) → Jinja template render with config-driven labels via a custom filter → response.

No async, no queue, no background workers. All I/O is synchronous on the request thread; this is acceptable for a single-user local app handling 300 people × 3000 sessions.

### 3.2 Package layout

```
flexlog/
  __init__.py
  __main__.py                    # `python -m flexlog`
  app.py                         # create_app() — Flask app factory
  config_loader.py               # loads + validates config.json
  paths.py                       # FLEXLOG_DATA_DIR resolution & sandboxed file-key API
  hashing.py                     # streaming SHA-256 for uploads
  db/
    __init__.py                  # engine, session factory, Base
    models.py                    # SQLAlchemy declarative models
  services/
    people.py                    # Person CRUD + dashboard aggregates
    sessions.py                  # Session CRUD + custom-rating handling
    media.py                     # upload pipeline, dedup, link/unlink
    library.py                   # Media Library queries (refs, orphans, hard delete)
    tags.py                      # tag normalization, lookup
  web/
    __init__.py                  # registers blueprints
    people_bp.py
    sessions_bp.py
    media_bp.py                  # serves uploaded files (sandboxed)
    library_bp.py                # Media Library views + actions
    forms.py                     # Flask-WTF forms with validators
    filters.py                   # Jinja filters (ui_string lookup, humanize, etc.)
  templates/                     # Jinja templates per page
  static/
    css/
    js/                          # page-scoped vanilla modules
    vendor/                      # cropperjs/, photoswipe/
tests/
  unit/                          # paths, hashing, config_loader, services
  integration/                   # routes hitting real tmp DB + tmp upload dir
  conftest.py
pyproject.toml                   # console_scripts: flexlog = flexlog.__main__:main
README.md
```

Source-code files are not part of `$FLEXLOG_DATA_DIR`. The data directory is strictly user data + config + DB.

## 4. Storage model

### 4.1 Disk layout

```
$FLEXLOG_DATA_DIR/
  config.json                          # user config (see §6)
  data/
    encounters.db                      # SQLite file
  uploads/
    .tmp/                              # transient incoming uploads, cleaned on success/failure
    ab/cd/abcd1234…wxyz.jpg            # one entry per unique file (by SHA-256)
    ab/cd/abcd1234…wxyz.mp3
    ...
```

`media_file.file_key` stores the relative path `"ab/cd/<sha256_hex>.<ext>"`. **No absolute paths in the database.** Sharding by the first two byte-pairs of the hash keeps any single directory under ~1000 entries even at 300k+ files (well above MVP scale).

Avatars and link thumbnails are stored under the same `media_file` table and the same `uploads/` tree — they are media. They appear in the Media Library alongside session media.

### 4.2 Sandboxed file access (`paths.py`)

All filesystem reads, writes, and deletes go through `paths.py`. It exposes:

- `data_dir() -> Path` — returns the validated `FLEXLOG_DATA_DIR`.
- `db_path()`, `config_path()`, `uploads_dir()`, `tmp_uploads_dir()`.
- `resolve_file_key(file_key: str) -> Path` — joins to `uploads_dir()`, calls `Path.resolve()`, asserts the resolved path is contained in `uploads_dir().resolve()`. Raises `ValueError` if the key escapes (e.g. `../../etc/passwd`). All media reads/writes use this function.
- `file_key_for(sha256_hex: str, mime_type: str) -> str` — produces the canonical `"<aa>/<bb>/<sha>.<ext>"`. Extension comes from a fixed allowlist mapped from MIME type.

The media-serving blueprint (`/media/<path:file_key>`) calls `resolve_file_key` before `send_from_directory`. Form-side filenames from the user are never used as keys — keys are derived purely from hash + extension.

### 4.3 Upload pipeline (`services/media.py`)

1. Stream the incoming file to `uploads/.tmp/<random>` while computing SHA-256 in chunks.
2. Validate: size ≤ `config.limits.max_upload_mb_per_file`; extension in allowlist; MIME from request header cross-checked against magic bytes for images; reject mismatches. Determine `media_type` (`photo` | `audio` | `video`) from MIME.
3. Compute `file_key = file_key_for(sha, mime)`.
4. **Dedup check:** if a `media_file` row with `sha256 == sha` exists, delete the temp file and return its `id`. **No second copy on disk.**
5. Else: ensure parent dirs exist; `os.replace(temp, target)` (atomic); insert `media_file` row.
6. Caller inserts the appropriate reference: a `session_media` row, a `person.avatar_media_id` set, or a `session_link.thumbnail_media_id` set.

`uploads/.tmp/` is swept of files older than 1 hour at app startup (covers crashed-mid-upload cleanup).

### 4.4 Allowed MIME / extension matrix

| Type | MIME | Extension |
|---|---|---|
| photo | image/jpeg | jpg |
| photo | image/png | png |
| photo | image/webp | webp |
| audio | audio/mpeg | mp3 |
| audio | audio/wav | wav |
| audio | audio/mp4, audio/x-m4a | m4a |
| video | video/mp4 | mp4 |
| video | video/webm | webm |
| video | video/quicktime | mov |

Anything outside the allowlist is rejected at upload time.

## 5. Retention model

This replaces PRD §6.10. The MVP behavior is **soft-unlink everywhere except the Media Library**.

### 5.1 Soft-unlink (the user's primary delete actions)

| User action | Effect on DB | Effect on disk |
|---|---|---|
| Remove individual media from a session | Delete `session_media` row | None |
| Replace person avatar | `person.avatar_media_id ← new (or NULL)` | None for old avatar |
| Remove link thumbnail | `session_link.thumbnail_media_id ← NULL` | None |
| Delete a session | Cascade-delete `session_media`, `session_link` (FK ON DELETE CASCADE) | None |
| Delete a person | Cascade-delete `session` → cascades into `session_media`, `session_link`, `person_tag` | None |

After any of these, the underlying `media_file` rows remain. They become **orphaned** if no remaining reference points to them.

### 5.2 Hard delete (Media Library only)

The Media Library route `/library` lists every `media_file` row. For each, the service computes a reference set:

```
refs(media_file_id) = {
  session_id   for session_media where media_file_id matches,
  person_id    for person where avatar_media_id matches,
  link_id      for session_link where thumbnail_media_id matches,
}
```

A media file with `len(refs) == 0` is an orphan.

The hard-delete action:
1. Confirmation dialog (text and reference count visible — "this file is currently linked to N sessions and M people").
2. Inside one DB transaction: delete `session_media` rows that reference it; null out `person.avatar_media_id` and `session_link.thumbnail_media_id` where they reference it; delete the `media_file` row. Commit.
3. After commit: `paths.resolve_file_key(...).unlink(missing_ok=True)`.

DB commits before the disk unlink. A failure between step 2 and 3 leaves an orphaned file on disk (recoverable manually) rather than a dangling DB row pointing at a deleted file.

### 5.3 Confirmation UX

- Delete a session: single confirmation dialog.
- Delete a person: stronger confirmation — type the alias to confirm (PRD §6.10 recommendation).
- Hard-delete from Media Library: confirmation dialog showing reference count and a warning that this is irreversible.

### 5.4 Reference computation performance

For 300 people × 3000 sessions × ~10 media each, the Media Library aggregate query joins three reference sources to `media_file`. Indexes on `session_media(media_file_id)`, `person(avatar_media_id)`, `session_link(thumbnail_media_id)` keep this fast. Reference count is computed per query, not denormalized — denorm adds bug surface for no current need.

## 6. Configuration

### 6.1 `FLEXLOG_DATA_DIR` (env var)

Required. Validated at startup:

- Must be set and non-empty.
- Must be an absolute filesystem path.
- Must exist (the app does **not** create the root — the user picks it deliberately).
- Must be readable and writable.

Child directories `data/`, `uploads/`, `uploads/.tmp/` are auto-created if missing. Any failure here is fatal at startup with a clear message naming the offending condition. Exit code 1.

`FLEXLOG_PORT` (optional, default 5050) selects the bind port. Host is always `127.0.0.1`.

`FLEXLOG_DEBUG=1` (optional, dev only) enables Flask debug mode.

### 6.2 `config.json` schema

Located at `$FLEXLOG_DATA_DIR/config.json`. Loaded once at startup; **no runtime reload** (PM default §13.5).

**First-run bootstrap:** if the file is missing, write the PRD §6.1 example as the default, log this fact, then load it. If the file exists but is malformed, fail. (This is a usability concession — the user can edit the bootstrapped file rather than hand-write JSON to first-run.)

Validation rules:

- `app.{name, entity_singular, entity_plural, session_singular, session_plural}` — required non-empty strings.
- `ratings` — list. ≤ 6 entries with `enabled: true` (PRD §6.1 acceptance). Each entry: `id` (slug-shaped, unique), `label` (string), optional `description`, `scale_min` ≥ 0, `scale_max` ≤ 5, `enabled` (bool). Duplicate IDs → fatal.
- `ui_strings` — dict of string→string. Missing keys fall back to a built-in default map keyed by the same names so the UI never renders an empty placeholder.
- `limits` — ints; `max_custom_rating_dimensions` ≤ 6; per-file/per-session caps applied at upload time.

All validation errors are collected and reported together (file path + line/key + reason) before exit. No partial start.

### 6.3 Label lookup

A Jinja filter `{{ "new_person" | ui }}` returns `app.config["FLEXLOG"].ui_strings.get("new_person", BUILTIN_DEFAULTS["new_person"])`. Entity and session labels are exposed as `entity.singular`, `entity.plural`, `session.singular`, `session.plural`. **No public-template wording is hardcoded** anywhere in routes, templates, or JS (PRD §6.1 acceptance).

### 6.4 Custom rating handling

`services/sessions.py` reads enabled rating dimensions from the loaded config to render the form. On save, only IDs currently enabled in the config are written to `custom_ratings_json`. On read for display, the page iterates the config's enabled IDs first; any extra keys present in stored JSON but absent from current config render under a collapsed "Archived ratings" group (PRD §6.1).

## 7. Data model

10 tables. UUID strings for IDs. Timestamps ISO-8601 UTC strings.

```sql
person (
  id              TEXT PRIMARY KEY,
  alias           TEXT NOT NULL,
  avatar_media_id TEXT REFERENCES media_file(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
)

tag (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  slug       TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
)
-- name compared case-insensitively; slug is the normalized lookup key

person_tag (
  person_id TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  tag_id    TEXT NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  PRIMARY KEY (person_id, tag_id)
)

session (
  id                  TEXT PRIMARY KEY,
  person_id           TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  session_date        TEXT NOT NULL,            -- YYYY-MM-DD
  overall_score       INTEGER NOT NULL CHECK(overall_score BETWEEN 0 AND 5),
  custom_ratings_json TEXT,                     -- {"clarity": 4, ...}
  notes               TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
)
INDEX session_person_date_idx ON session(person_id, session_date DESC)

session_link (
  id                  TEXT PRIMARY KEY,
  session_id          TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
  url                 TEXT NOT NULL,
  label               TEXT,
  thumbnail_media_id  TEXT REFERENCES media_file(id) ON DELETE SET NULL,
  sort_order          INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL
)

media_file (
  id                TEXT PRIMARY KEY,
  sha256            TEXT NOT NULL UNIQUE,        -- 64 hex chars
  file_key          TEXT NOT NULL,               -- "ab/cd/<sha>.<ext>"
  media_type        TEXT NOT NULL,               -- 'photo' | 'audio' | 'video'
  original_filename TEXT,                        -- first-seen wins; preserved for display
  mime_type         TEXT NOT NULL,
  file_size_bytes   INTEGER NOT NULL,
  created_at        TEXT NOT NULL
)

session_media (
  id            TEXT PRIMARY KEY,
  session_id    TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
  media_file_id TEXT NOT NULL REFERENCES media_file(id) ON DELETE CASCADE,
  sort_order    INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  UNIQUE (session_id, media_file_id)
)
```

Indexes (declared via SQLAlchemy `Index(...)` and emitted by `Base.metadata.create_all()`):

- `session(person_id, session_date DESC)` — feeds person-detail session list and dashboard "last session" aggregate
- `session_media(media_file_id)` — feeds Media Library reference lookups
- `person(avatar_media_id)` — feeds Media Library reference lookups
- `session_link(thumbnail_media_id)` — feeds Media Library reference lookups
- `tag(slug)` — already unique, used for tag normalization lookup

### 7.1 Cascade rationale

- **`session.person_id ON DELETE CASCADE`**: deleting a person removes their sessions, which in turn cascades to `session_media` and `session_link` rows. `media_file` rows survive (they're outside the cascade).
- **`avatar_media_id` / `thumbnail_media_id` ON DELETE SET NULL**: when a `media_file` is hard-deleted from the Media Library, references that survive (avatar, link thumbnail) become null instead of cascading their parent rows to deletion.
- **`session_media.media_file_id ON DELETE CASCADE`**: when a `media_file` is hard-deleted, its session_media join rows go with it.
- **`person_tag` cascades** so deleting a person cleans up tag joins.

### 7.2 Custom ratings as JSON, not a table

Custom rating values are stored as a JSON object on the session row (`custom_ratings_json`). This keeps the schema stable when rating dimensions change in `config.json` — disabled or removed dimension IDs still survive in stored sessions and render under "Archived ratings". A separate `session_rating` table would force schema migrations on every config change, which we don't want.

## 8. Routes

Per PRD §7, with additions for the Media Library.

```
GET  /                                   Dashboard (people grid/list)
GET  /people/new                         Add Person form
POST /people                             Create Person
GET  /people/<person_id>                 Person Detail (sessions list)
GET  /people/<person_id>/edit            Edit Person form
POST /people/<person_id>                 Update Person
POST /people/<person_id>/delete          Delete Person (cascades sessions; unlinks media)

GET  /people/<person_id>/sessions/new    Add Session form
POST /people/<person_id>/sessions        Create Session
GET  /sessions/<session_id>              Session Detail
GET  /sessions/<session_id>/edit         Edit Session form
POST /sessions/<session_id>              Update Session
POST /sessions/<session_id>/delete       Delete Session (unlinks media)

POST /sessions/<session_id>/media/<media_file_id>/unlink   Remove media from this session
POST /session_links/<link_id>/delete                       Remove link from session

GET  /library                            Media Library (filters: type, orphans)
POST /library/<media_file_id>/hard_delete  Hard delete file + remaining refs

GET  /media/<path:file_key>              Serve uploaded file (sandboxed)
```

CSRF tokens on every POST. All POST endpoints flash a result message and redirect.

## 9. Security & privacy

| Concern | Control |
|---|---|
| Network exposure | Bind `127.0.0.1`; debug off by default |
| CSRF | Flask-WTF on every mutating form. Secret key generated and persisted to `$FLEXLOG_DATA_DIR/.secret_key` (mode 0600) on first run |
| XSS | Jinja autoescape on; user text rendered as text only; no `\|safe` on user input; newlines in notes shown via CSS `white-space: pre-wrap` |
| Path traversal | All disk access via `paths.resolve_file_key`; uploaded filenames never used as keys |
| File validation | Size cap from config; extension allowlist; MIME magic-byte check for images; mismatches rejected |
| External links | `target="_blank" rel="noopener noreferrer"`; app never fetches them |
| Outbound network | No code path makes outbound HTTP. Verified manually for MVP; lint check optional post-MVP |
| CDNs | None. All JS/CSS local, vendored under `static/` |
| Telemetry | None |

## 10. Error handling

- **Startup errors are fatal and chatty.** Missing/relative/unwritable `FLEXLOG_DATA_DIR`, malformed `config.json`, unrunnable migration → print a clear message naming the offending key/path and exit 1. No partial start.
- **Form validation errors** re-render the form with field-level errors via Flask-WTF.
- **CSRF failure** → 400 page with clear copy.
- **System errors** (disk full, DB locked, hash mismatch on resume) → flash + log, render a friendly error page. Stack traces never exposed in non-debug.
- **404 / 405 / 500** templated, copy honors config labels.
- **Logging:** stdlib `logging` to stderr at INFO. No file logging in MVP.

## 11. Testing strategy

### 11.1 Tooling

- pytest, real SQLite, real tmp filesystem. No mocks of DB or filesystem.
- `pytest-cov` configured in `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  addopts = "--cov=flexlog --cov-report=term-missing --cov-fail-under=85"
  ```
- **The 85% line-coverage gate is enforced.** A test run that drops below fails CI/local.

### 11.2 Fixtures (`conftest.py`)

- `tmp_data_dir` — uses `tmp_path`; sets `FLEXLOG_DATA_DIR`; writes a default `config.json`; yields the path.
- `app` — `create_app()` against `tmp_data_dir`.
- `client` — `app.test_client()`.
- `db_session` — SQLAlchemy session bound to the tmp DB.

### 11.3 Test layers

- **Unit** (`tests/unit/`): `paths` (sandboxing, file-key generation, traversal rejection), `hashing` (deterministic streaming SHA-256), `config_loader` (validation matrix: missing keys, malformed JSON, >6 enabled ratings, duplicate IDs), `services/library` (ref-count math, orphan detection).
- **Integration** (`tests/integration/`): full route flows via test client. Mandatory cases:
  - Create person → upload photo → upload identical bytes → assert single `media_file` row, single file on disk.
  - Unlink media from session → assert `session_media` gone, `media_file` and disk file persist; Media Library shows it as orphan.
  - Hard-delete from Media Library → file gone from disk + cascades clean.
  - Avatar replace → old avatar becomes orphan; new avatar appears in Media Library.
  - Person delete (cascade) → sessions/joins gone; media files persist.
  - Chinese notes round-trip (UTF-8).
  - Search by alias and by tag.
  - Sort by all enabled options.
  - Path-traversal upload attempt rejected.
  - XSS attempt in notes/aliases rendered as text.
  - CSRF token absent → 400.
  - `FLEXLOG_DATA_DIR` missing/relative/unwritable → app fails to create.

### 11.4 Coverage discipline

Critical paths target ≥95% coverage: `paths`, `hashing`, `config_loader`, `services/media`, `services/library`, `services/sessions` (custom ratings handling). Templates and trivial getters are still covered by integration tests. The 85% floor is a global gate; individual modules may exceed it.

## 12. Milestone breakdown

Each milestone is its own sub-spec → plan → implementation cycle.

### M1 — Foundation
Project skeleton; `paths.py`, `config_loader.py`, `hashing.py`; app factory; base template `_base.html` with config-driven labels; pyproject; pytest scaffolding with the coverage gate; `python -m flexlog` runner. **Deliverable:** `flexlog` starts against a tmp `FLEXLOG_DATA_DIR`, serves a placeholder dashboard, fails fast on bad config. No domain models yet.

### M2 — People + tags
Models: `person`, `tag`, `person_tag`. Person CRUD blueprint, dashboard list (placeholder aggregates), search by alias/tag, tag chip UI, person detail page (empty session list). Avatar upload deferred to M5.

### M3 — Sessions, ratings, notes
Models: `session`, `session_link`. Session CRUD blueprint, custom-rating form rendering from config, archived-ratings handling, link manager (URL + label only — link thumbnails come with M4 media). Person detail shows real session list. Dashboard aggregates (last session date, count, avg score) light up.

### M4 — Media + Media Library
Models: `media_file`, `session_media`. Upload pipeline with hash dedup. Inline `<audio>` / `<video>` players. PhotoSwipe carousel + lightbox on session detail. Media Library route `/library` with type/orphan filters and hard-delete action. Link thumbnails (uses the same upload pipeline).

### M5 — Avatar cropper + sort + polish
Cropper.js avatar flow (uses M4 pipeline; avatars land in Media Library). Dashboard sort-by options. Empty states, error pages, accessibility pass, README with backup/restore + run instructions. Final QA-checklist sweep against PRD §12.

### Sequencing
M1 unblocks everything. M2 → M3 (M3 needs `person_id`). M3 → M4 (M4 hangs media off sessions). M4 → M5 (M5 cropper uses M4 upload pipeline).

## 13. PRD deviations

Two deliberate deviations from the PRD:

1. **Disk layout.** PRD §6.3 specifies `uploads/<person_id>/<session_id>/photos/...`. We use content-addressed sharding (`uploads/<aa>/<bb>/<sha>.<ext>`) because content-hash dedup makes per-session ownership ambiguous (one file can belong to many sessions). The PRD's portable-storage-key intent (§14.12) is preserved — keys remain relative, not absolute.

2. **Delete semantics.** PRD §6.10 specifies hard cascades on session/person delete. We use soft-unlink + Media Library hard-delete because the user explicitly requested it. Acceptance criteria from PRD §6.10 are reinterpreted: "deletes session/person" still removes them from history and dashboard, but media persists on disk and in the Media Library until hard-deleted there.

All other PRD requirements (no external services, no telemetry, no CDN, UTF-8 notes, configurable labels, 300×3000 scale, etc.) hold unchanged.

## 14. QA mapping

PRD §12 checklist items 1–24 each map to at least one integration test. The mapping is maintained inline in test docstrings (e.g. `# QA-18: copy data dir + new env var preserves data`). M5 includes a final sweep where every QA item is run end-to-end manually as well.

---

**End of design.**
