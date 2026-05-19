# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All targets are wrapped in the Makefile and run inside `.venv/`:

```bash
make install          # one-time: create .venv + install hash-pinned deps
make run              # run app at http://127.0.0.1:5050/ against ./flexlog-data/
make test             # full pytest suite (85% coverage gate enforced)
make test-cov         # same + term-missing report
make smoke            # boot against /tmp dir, hit /, assert files were created
make lock             # regenerate requirements.lock from pyproject.toml (maintainer)
make audit            # pip-audit --strict against requirements.lock (maintainer)
make openapi          # validate docs/openapi.yaml + run drift tests
make clean            # nuke .venv + caches
```

Overrides: `make run DATA_DIR=$HOME/flexlog-data PORT=5151`, `make install PYTHON=python3.13`.

`make install` enforces dep integrity: `pip install --require-hashes -r requirements.lock` refuses to install a package whose downloaded bytes don't match the recorded sha256. After pip, the same target runs `sha256sum -c flexlog/static/vendor/INTEGRITY.txt` (or `shasum -a 256 -c` on macOS) — drift in any vendored JS/CSS file fails the install loudly. Together those are the install-time supply-chain defenses.

`make audit` and `make lock` are **maintenance commands** that need outbound network (OSV vuln DB for audit, PyPI for lock). The running app itself makes zero outbound requests — that property is asserted by `tests/integration/test_qa_checklist.py::test_qa_02_no_third_party_requests`.

**Single test** (no make wrapper — call pytest directly):
```bash
.venv/bin/python -m pytest tests/unit/test_crypto.py::test_argon2id_kek_is_deterministic -v --no-cov
```

The `--no-cov` flag skips the coverage gate; useful for quick iteration. Without it, pytest enforces ≥85% via `pyproject.toml`'s `--cov-fail-under=85` in `addopts`. The gate is intentional — `feedback_test_coverage.md` in saved memory codifies it.

**Coverage falls below 85% → fix it.** This is enforced; don't bypass with `--no-cov` in CI.

## Where data lives

Everything is under one directory pointed at by `$FLEXLOG_DATA_DIR` (must be absolute; `flexlog/paths.py` validates at boot):

```
$FLEXLOG_DATA_DIR/
├── config.json           # app labels, rating dimensions (with weights), UI strings, limits (schema_version=3)
├── kdf_params.json       # Argon2id salt, KEK nonce, wrapped master key (0600, plaintext but useless without password)
├── .secret_key           # Flask SECRET_KEY for cookie signing (not user data)
├── data/encounters.db    # SQLCipher-encrypted SQLite DB
└── uploads/<hh>/<hh>/<sha>.<ext>   # AES-GCM chunked media files
                                    # (.tmp/ subdir holds in-flight uploads;
                                    # tmp_sweep at startup drops >24h-old files)
```

Atomic writes to anything sensitive use `paths.atomic_write_text(path, content, mode=0o600)` (added in v0.8.0). It does `O_EXCL`-create with a randomized tmp suffix → write + flush + fsync → `os.replace`. The randomized suffix prevents crash-loop on stale tmp files. Used by `config_loader`, `secret_key`, `settings_bp` (config writes), `kdf_params`. Don't reimplement the pattern — call the helper.

## Architecture (read this before editing)

### Encryption-at-rest is the core constraint

The app's design hinges on one fact: **the encryption keys exist only in process memory after login.** Anonymous routes (landing, static, setup) never touch the DB — the engine isn't attached until the user submits the right password.

Key hierarchy (`flexlog/crypto.py`):

```
password ──Argon2id(salt)──► KEK ──AES-GCM-unwrap(nonce, wrapped_master)──► master_key
                                                                                │
                                            ┌───────────────────────────────────┤
                                            ▼                                   ▼
                              HKDF(info=b"flexlog/sqlcipher/v1")   HKDF(info=b"flexlog/fek/v1", sha256)
                                            │                                   │
                                            ▼                                   ▼
                                  SQLCipher PRAGMA key              per-file FEK (AES-GCM, chunked)
```

`kdf_params.json` is the only thing on disk that mentions the password — and it stores **only** the salt, nonce, and AES-GCM-wrapped master key. Without the password, the wrapped blob is opaque.

### Engine attached at login, not at boot

`flexlog/app.py:create_app()` does NOT call `attach_to_app()`. It registers `register_db_teardown(app)` (so the per-request DB session close fires regardless of when the engine was attached), then leaves `app.config[_ENGINE_KEY]` unset. The auth gate redirects every non-allowlisted route to `/` when unauthed.

`landing_bp.submit` (and `setup_bp.set_password`) is where the engine actually gets attached: load `kdf_params.json` → Argon2id(password) → unwrap master key → derive SQLCipher passphrase → `make_engine()` → `attach_engine_at_runtime()`. The latter also calls `migrate_to_latest()` which runs `migrate_v1_to_v2` plus `repair_dangling_session_fk_refs` (idempotent).

If you're adding a route that touches the DB: it must not be in `ALLOWED_UNAUTH_ENDPOINTS` (in `flexlog/auth.py`). The gate redirects it to `/`, which means the engine isn't attached and `get_db()` raises `RuntimeError`.

### Request flow

```
HTTP request
   │
   ▼
@app.before_request: _gate()
   ├─ in ALLOWED_UNAUTH_ENDPOINTS or "setup.*"  →  let through
   ├─ session.authed && session.epoch == app.config["AUTH_EPOCH"]  →  let through
   └─ otherwise  →  redirect("/")
   │
   ▼
route handler
   ├─ calls get_db() for ORM access  (lazy session-per-request via flask.g)
   ├─ calls upload_to_media_file()   (streams + encrypts + dedups by SHA-256)
   └─ renders template OR returns JSON
   │
   ▼
@app.teardown_appcontext: close_db()
```

`AUTH_EPOCH` is regenerated by `secrets.token_hex(16)` on every `create_app()` call. Cookies signed before a restart become invalid — forces re-login + re-derivation of the master key.

### Package layout (what each thing owns)

```
flexlog/
├── app.py              # create_app(): wires config, CSRF, blueprints, auth gate, error handlers,
│                        #               security headers, Jinja filters, status-bar ctx processor
├── __main__.py         # `flexlog` CLI entry — reads FLEXLOG_PORT, runs app.run(host="127.0.0.1")
├── paths.py            # ALL filesystem I/O sandboxed here — validates FLEXLOG_DATA_DIR, resolves
│                        #   file_keys, atomic_write_text() helper for sensitive writes
├── crypto.py           # Argon2id, AES-GCM, HKDF, chunked file encrypt/decrypt — zero Flask imports
│                        #   encrypt_file_to_path fsync's the destination before close (v0.8.2 M4)
├── kdf_params.py       # read/write kdf_params.json (atomic O_EXCL 0600 + rename)
├── secret_key.py       # load_or_create_secret_key() — Flask SECRET_KEY persisted to .secret_key
├── config_loader.py    # validate_config_dict() + load_or_bootstrap() + v1/v2→v3 config auto-upgrade
│                        #   (writes use atomic_write_text — pre-v0.8.0 truncate-then-write left
│                        #    zero-byte config.json on crash)
├── auth.py             # is_authed(), mark_authed(), looks_like_sensitive_info() — pure functions, no Flask
├── hashing.py          # streaming SHA-256
├── migrations/
│   └── v1_to_v2.py     # migrate_to_latest() runs on every engine attach. Refuses to attach if
│                        #   user_version > TARGET_VERSION (catches downgrades). MigrationError →
│                        #   friendly error page.
├── db/
│   ├── __init__.py     # make_engine(), get_db(), attach_engine_at_runtime(),
│   │                    #   detach_engine_at_runtime() (called on logout), engine_is_attached()
│   │                    #   — NullPool (see comment)
│   └── models.py       # Person, Tag, PersonTag, Session, SessionLink, MediaFile, SessionMedia
├── services/           # business logic — accept (db, ...) args, no Flask imports beyond current_app for config
│   ├── auth.py         # bootstrap_state(data_dir): "needs_setup" | "needs_recovery" | "ready"
│   ├── people.py       # CRUD + list_dashboard_rows() + Python-side custom-dim averaging for sort
│   ├── sessions.py     # CRUD + link_media_to_session() (idempotent on (session_id, mf_id))
│   │                    #   + split_ratings() + _replace_links(urls, thumb_keys) with
│   │                    #     is_safe_link_url() http(s)-only allowlist
│   ├── media.py        # upload_to_media_file() pipeline: stream → SHA → magic byte (incl. audio/video)
│   │                    #   → HEIC transcode (with 50MP cap) → dedup → encrypt.
│   │                    #   Catches IntegrityError on concurrent SHA dedup race; unlinks target on
│   │                    #   other DB-flush failures so orphans don't accumulate.
│   ├── library.py      # hard_delete() — the ONLY code path that removes a file from disk.
│   │                    #   Refuses if any reference exists (raises MediaInUseError).
│   │                    #   Module-level @event.listens_for(Session,"after_commit") drains
│   │                    #   pending_unlinks per session (no per-call listener accumulation).
│   ├── status.py       # compute_status(db, data_dir) → StatusSnapshot(storage_bytes,
│   │                    #   last_session_at) for the v0.8.0 status bar. + humanize_bytes()
│   └── tags.py         # global tag CRUD (intentionally no cascade — see Person.tags note in models.py)
├── web/                # blueprints (Flask routes). Each owns the request-shape concerns, delegates to services.
│   ├── landing_bp.py   # GET/POST / — fake Google clone + login submit handler. Has the engine-attach logic.
│   │                    #   _looks_like_password heuristic has NO upper length bound (v0.8.2 M1 fix
│   │                    #   — long passphrases no longer leak to google.com/search?q=).
│   ├── setup_bp.py     # /setup/* — first-run set-password + recover-orphaned-plaintext-data pages
│   ├── auth_bp.py      # POST /logout — clears MASTER_KEY from app.config + calls
│   │                    #   detach_engine_at_runtime so a bug in the unauth allowlist can't reach data
│   ├── dashboard_bp.py # GET / (when authed) + /dashboard — search + sort dropdown wired to config.ratings[].sortable
│   ├── people_bp.py    # /people/* — CRUD + avatar dataURL cropper backend (decode → upload pipeline)
│   ├── sessions_bp.py  # /sessions/* — new/create/edit/update/destroy + session-link CRUD
│   │                    #   form carries parallel link_urls[] + link_thumb_keys[] (v0.7.0 paste model)
│   ├── media_bp.py     # /media/<file_key> — Range-aware streaming decrypt
│   ├── library_bp.py   # /library — list + filter + hard-delete (returns 303 + flash on MediaInUseError)
│   ├── settings_bp.py  # /settings — 5 tabs (App / Ratings / UI strings / Limits / Raw JSON) + change-password
│   │                    #   change_password uses hmac.compare_digest for the master-key consistency check
│   ├── upload_bp.py    # POST /sessions/upload + DELETE /sessions/upload/<file_key> — AJAX progressive upload
│   ├── security_headers.py # register_security_headers(app) — CSP + 4 sibling headers via @after_request
│   ├── vendor_integrity.py # auto-generated SRI_HASHES dict; consumed by the vendor_sri Jinja filter
│   ├── forms.py        # Flask-WTF forms (thin, only enforce presence/length; services do real validation)
│   └── filters.py      # Jinja filters: `ui`, `overall_fmt`, `star_fill`, `humanize_bytes`,
│                        #   `iso_local_minute`, `vendor_sri`. + label context processor.
└── templates/          # Jinja2 templates. _base.html ships <meta name="csrf-token"> so JS can read it.
                        # NO inline `on*=` event handlers (CSP `script-src 'self'` blocks them);
                        # use data-* attrs handled by static/js/csp_handlers.js. Tripwire test:
                        # tests/integration/test_no_inline_event_handlers.py.
```

Top-level helpers/scripts:

```
scripts/
└── regen_vendor_integrity.py  # walks flexlog/static/vendor/, writes INTEGRITY.txt (sha256 manifest
                                #   used by `make install`) + flexlog/web/vendor_integrity.py
                                #   (sha384-base64 SRI_HASHES dict consumed by the vendor_sri filter).
                                # Run after updating any vendored JS/CSS file; commit both outputs.

requirements.lock              # hash-pinned dep lockfile (committed). Generated by `make lock`
                                #   (pip-compile --generate-hashes --extra dev). Install enforces hashes.
```

### Sessions form upload flow (the AJAX bit)

When the user adds a photo on the new/edit session page:

1. Browser uploads to `POST /sessions/upload` immediately (per file, via `XMLHttpRequest` for progress events).
2. `upload_bp.upload` runs `upload_to_media_file` → returns `{file_key, mime, ...}` as JSON.
3. `static/js/session_form.js` appends a `<li>` row with a hidden `<input name="photo_keys" value="<file_key>">` to the form.
4. On Save, `sessions_bp.create`/`update` reads `request.form.getlist("photo_keys")`, calls `link_media_to_session(...)`.
5. `link_media_to_session` is **all-or-nothing on unknown keys** (returns `(0, unknown_list)` for the route to surface as 422 + form re-render) AND **idempotent on already-linked pairs** (edit form re-submits existing media's hidden inputs; we skip the SessionMedia UNIQUE collision).

The CSRF token is exposed via `<meta name="csrf-token">` in `_base.html`; JS reads it once and sets `X-CSRFToken` on every XHR. Flask-WTF accepts that header by default.

### Link thumbnails (paste model, v0.7.0)

Link rows in the session form are click-to-focus cards. The user pastes (⌘V / Ctrl+V) or drag-drops a screenshot onto the card; `session_form.js` uploads the image via the same `/sessions/upload` endpoint (kind=photo) and stores the returned `file_key` in a hidden `<input name="link_thumb_keys">` parallel to the URL's hidden `<input name="link_urls">`.

On save, `sessions_bp` reads both lists, passes them to `create_session(link_urls=..., link_thumb_keys=...)` → `_replace_links` pairs them and sets `SessionLink.thumbnail_media_id`. Server-side rules:

- `is_safe_link_url(url)` allowlists only `http://` and `https://`. `javascript:`, `data:`, `file:`, etc. URLs are silently dropped (client validates too; the server is defense-in-depth).
- Non-photo `MediaFile` referenced as a link thumb → silently dropped (defense against hand-crafted POSTs that try to reference an audio/video as a thumbnail).
- Unknown file_keys → silently dropped.
- The detail page renders link thumbnails in their own PhotoSwipe gallery (`#link-thumb-gallery`) separate from the photos section.

There is no auto-fetch. v0.6.0 tried headless Chromium for OG-image / screenshot extraction; real-world pages defeated it (lazy-load, paywalls, captchas, SPAs). The paste model removed Playwright (~280 MB) and gives the user direct control.

### Media pipeline specifics

`flexlog/services/media.py:upload_to_media_file`:

- Streams to a tmp file under `paths.tmp_uploads_dir()`, computing SHA-256 + size as it goes.
- Magic-byte cross-check on **images** (JPEG / PNG / WebP / HEIC) — declared MIME must match the file's actual signature.
- Magic-byte container check on **audio/video** (`_looks_like_audio_video`, v0.8.2 M4) — rejects HTML/PHP/JS polyglots declared as audio/mp4. The check is coarse (`audio/mp4` and `video/mp4` share `ftyp` brands so strict type-distinction isn't possible from 64 bytes) but rejects non-A/V signatures.
- **HEIC → JPEG transcode** before storage (so non-Safari browsers can render). Resolution-preserving: `quality=95, subsampling=0`. Checks declared pixel count BEFORE `img.load()` and rejects if `width × height > 50_000_000` (v0.8.2 M5 — decompression-bomb defense; iPhone 14 Pro main camera is ~48 MP). `pillow-heif` registers as a Pillow opener at module load; if `libheif` is unavailable, HEIC uploads raise `UnsupportedMediaTypeError` instead of crashing the app.
- Dedup by SHA-256 → reuse existing `MediaFile` row if hit.
- Encrypt via `crypto.encrypt_file_to_path` (chunked AES-GCM: 16-byte `FLE0` header + 64 KiB chunks each with a 16-byte GCM tag, range-decryptable). The destination file is `flush()` + `os.fsync()`'d before close (v0.8.0 M4 — power-loss durability).
- Insert `MediaFile` row, return it. Caller commits.

Failure handling around the insert (v0.8.0 I2 + I5):

- `IntegrityError` on the dedup unique constraint → another writer raced us; rollback, reload the existing row by SHA, return it. The on-disk encrypted bytes are identical (deterministic FEK).
- Any other `Exception` from `db.flush()` → unlink the encrypted target before re-raising, so orphans don't accumulate from disk-full or FK-violation failures.
- Race-on-the-race (both writers somehow roll back; effectively impossible under SQLite write serialization) → `MediaUploadError("upload dedup conflict; retry")` rather than `NoResultFound`.

`flexlog/web/media_bp.py` serves decrypted bytes with range support — PhotoSwipe/video players send `Range: bytes=N-M` headers; the handler seeks to the relevant chunks, decrypts only those, slices to exact bytes.

### Settings page architecture

`/settings` has five tabs (App / Ratings / UI strings / Limits / Raw JSON). Each tab posts to `POST /settings/<section>`. The handler:

1. Builds `merged = _config_as_dict()` from the current live `Config` dataclass.
2. Overwrites the submitted section's keys.
3. Runs `validate_config_dict(merged)` (shared with `load_config`).
4. On failure: re-renders the tab with field errors. No disk write.
5. On success: atomic write to `config.json` (`O_EXCL` 0600 tmp + fsync + rename), then `current_app.config["FLEXLOG"]` is replaced in-place. Changes take effect on the next request.

Ratings tab carries a hidden `rating_original_id` per row so renames are detectable. If an `original_id` is in use (any session's `ratings_json` references it) and differs from the new `id`, the save returns 422 with a "cannot rename — in use" error. Deletes are allowed (sessions with deleted dims show them under "Archived ratings" on detail).

### Test architecture

`tests/conftest.py` builds an encrypted data dir per test via `tmp_data_dir` fixture using **weak Argon2 params** (`time=1, memory=8 KiB`) — production Argon2id-per-fixture would push the suite from ~10s to ~50s. Real password verification still goes through Argon2id, just with cheap parameters.

Important fixtures:

- `app` (CSRF disabled), `client`, `db_session`, `authed_client` — for non-CSRF flow tests.
- `csrf_app`, `csrf_client`, `csrf_db_session`, `csrf_authed_client`, `csrf_person` — for CSRF-relevant tests. Use these for anything that POSTs through Flask-WTF.
- `_FIXTURE_PASSWORD = "hunter2-test"` is the bootstrapped admin password; `admin_password` fixture returns it.

The `app` fixture's `_bootstrap_encrypted_dir` does `Base.metadata.create_all(engine)` then stamps `PRAGMA user_version = 2` so the on-attach migration is a no-op on a freshly-built v2-shape DB. Real v0.2.0 user DBs (with rows) get the full restructure via `migrate_v1_to_v2`'s table-rebuild path.

`tests/integration/test_db_threaded.py` exists specifically to catch SQLCipher thread-safety regressions — if you change the pool config, run it.

### Auth model and the fake landing page

`GET /` and `POST /` are the **only** unauthed endpoints besides `/setup/*` and `/static/*`. The page looks like Google. The POST handler:

1. If the query is the admin password → unlock master key, attach engine, mark session authed, redirect to `/dashboard`.
2. If the query "looks sensitive" (password-shape / SSN / Luhn-valid CC via `looks_like_sensitive_info`) → redirect to `https://www.google.com/` (homepage, not search) so the typed string doesn't end up in Google's search logs.
3. Otherwise → 303 to `https://www.google.com/search?q=<typed>` so the page acts like the real Google clone.

The fake landing is UX cover, not a security primitive. There's no rate limiting; Argon2id KDF cost is the only brute-force defense. For hostile public exposure, this app needs a reverse proxy with rate limiting in front — or, more practically, Tailscale.

### Status bar (v0.8.0)

Every authed page renders a sticky-footer status bar showing total `$FLEXLOG_DATA_DIR/` size + last session save timestamp. The wiring:

- `flexlog/services/status.py:compute_status(db, data_dir)` returns a `StatusSnapshot(storage_bytes, last_session_at)`. One SQL `MAX(session.updated_at)` + one `rglob` walk of the data dir.
- `flexlog/app.py:_inject_status_snapshot` is a `@app.context_processor` that calls compute_status only when authed + engine attached. Catches any exception → logs a warning → injects nothing (the page renders without the bar; never crashes).
- `flexlog/templates/_partials/status_footer.html` renders the bar via the `humanize_bytes` and `iso_local_minute` Jinja filters.

No schema change was needed — `Session.updated_at` already existed in the model. SQLAlchemy's `onupdate` fires whenever `update_session` SETs any column on the parent row; the regression test in `tests/unit/test_status_service.py::test_session_updated_at_bumps_on_update_session` guards against a future refactor that touches only the links relationship.

### Security headers + CSP (v0.8.2)

`flexlog/web/security_headers.py:register_security_headers(app)` installs an `@app.after_request` hook that adds these on every response:

- `Content-Security-Policy: default-src 'self'; script-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: geolocation=(), camera=(), microphone=(), payment=(), usb=()`

`script-src 'self'` (no `'unsafe-inline'`) is the load-bearing directive — it blocks XSS from executing inline scripts even if user input reaches the DOM. **Templates must not use inline `on*=` event handlers** (CSP silently drops them). Use `data-auto-submit` / `data-nav-on-change="URL_TEMPLATE"` / `data-confirm="MSG"` attributes handled by `flexlog/static/js/csp_handlers.js`. Tripwire test `tests/integration/test_no_inline_event_handlers.py` walks every template and fails on any `on*=` attribute.

`style-src` keeps `'unsafe-inline'` because some templates use inline `style="..."` attributes (cropper widget, ARIA helpers). Tightening requires a CSS audit pass — not done.

### Supply-chain hygiene (v0.8.2)

Three install-time + runtime defenses:

1. **Hash-pinned dep lock.** `requirements.lock` is generated by `make lock` (pip-compile --generate-hashes --extra dev). `make install` enforces hashes via `pip install --require-hashes`. A hijacked PyPI version of any pinned dep fails the install.

2. **Vendored-JS integrity.** `flexlog/static/vendor/INTEGRITY.txt` is a sha256 manifest of every vendored JS/CSS file, regenerated by `python scripts/regen_vendor_integrity.py`. `make install` runs `sha256sum -c` (or `shasum -a 256 -c` on macOS) and fails on drift. Templates also emit `integrity="sha384-..."` SRI attributes via the `vendor_sri` Jinja filter so the browser refuses tampered files at parse time.

3. **CVE audit.** `make audit` runs `pip-audit --strict` against the lock. Treat it as a release gate. Needs outbound network (OSV DB).

When updating a vendored asset:
```bash
# 1. Replace the file under flexlog/static/vendor/
# 2. Regenerate both manifests
python scripts/regen_vendor_integrity.py
# 3. Commit the file change + INTEGRITY.txt + vendor_integrity.py together
```

When bumping a Python dep:
```bash
# 1. Edit pyproject.toml
make lock        # regenerates requirements.lock from pyproject.toml
make audit       # confirm no CVEs in the new resolved set
# 2. Commit pyproject.toml + requirements.lock together
```

### HTTP API spec (OpenAPI 3.0)

`docs/openapi.yaml` is the source of truth for every Flask route flexlog
exposes — 34 operations across 11 blueprints, with parameters, request
bodies, response codes, and auth requirements documented per operation.

The spec is enforced by `tests/integration/test_openapi.py`, which:

- Validates the spec against the OpenAPI 3.0 schema (catches malformed
  YAML / missing required fields).
- Walks `app.url_map` and fails on any route NOT in the spec (catches
  "added a route, forgot to doc it").
- Walks the spec and fails on any path NOT in `url_map` (catches
  "removed a route, forgot to remove the doc").
- Compares HTTP methods, `operationId` ↔ Flask endpoint names, and
  the `security: []` annotation against `ALLOWED_UNAUTH_ENDPOINTS`.
- Surfaces any operation marked `deprecated: true` and requires it to
  carry `x-removal-version: "X.Y.Z"` for changelog tracking.

When you add or change a route:
1. Update the route handler.
2. Update `docs/openapi.yaml` with the new path / method / responses.
3. Run `make openapi` to validate + drift-check.
4. Commit the route change + spec change together.

When you deprecate a route:
1. Add `deprecated: true` and `x-removal-version: "X.Y.Z"` on the
   operation in `docs/openapi.yaml`.
2. The README's next changelog section lists the planned removal.
3. When `X.Y.Z` ships, remove the route + the spec entry in one commit.

Drift tests run as part of the normal `make test` suite; `make openapi`
is a quick-feedback target that validates spec + runs only the drift
tests, useful while iterating on route changes.

## Conventions

- **`paths.py` owns all disk paths.** Don't `Path(os.environ[...])` elsewhere. Don't `os.path.join` filesystem roots.
- **Atomic writes via `paths.atomic_write_text(path, content, mode=0o600)`.** O_EXCL + fsync + os.replace with a randomized tmp suffix. Used by `config_loader.load_or_bootstrap`, `secret_key.load_or_create_secret_key`, `settings_bp._atomic_write_config`. Don't reimplement.
- **Services take `db: Session` as the first arg.** No `current_app.config[...]` lookups inside services for DB access. They may read `current_app.config["FLEXLOG"]` for app config + `current_app.config["MASTER_KEY"]` for crypto.
- **Routes are thin.** Parse form → call service → render template. Validation lives in services, not in route handlers, except for form-shape validation (Flask-WTF).
- **Templates pull labels via `{{ "<key>" | ui }}`.** Don't hardcode user-facing strings in templates; add a key to `BUILTIN_UI_DEFAULTS` in `flexlog/web/filters.py` so the user can override it via `config.json` or the Settings UI.
- **No inline `on*=` event handlers in templates.** CSP `script-src 'self'` blocks them. Use `data-auto-submit` / `data-nav-on-change` / `data-confirm` attributes handled by `static/js/csp_handlers.js`. Tripwire test enforces this.
- **No inline `<script>` blocks in templates.** Same CSP rule. All JS lives in `flexlog/static/js/*.js` and is loaded via `<script src=...>` tags. Vendored JS additionally carries `integrity="sha384-..."` via the `vendor_sri` filter.
- **Migrations are idempotent.** `migrate_to_latest` runs on every engine attach. Any new migration must be safe to re-run on an already-migrated DB. Will refuse to attach if `user_version > TARGET_VERSION` (catches downgrades).
- **Avoid mocks in DB tests.** From saved memory (`feedback_testing` style): integration tests hit a real SQLCipher DB via the conftest fixtures. Don't mock SQLAlchemy.
- **Dep bumps need a lock regen.** Edit `pyproject.toml` → `make lock` → `make audit` → commit both together. The Makefile install enforces hashes, so a stale lock breaks `make install`.
- **Vendored asset updates need a manifest regen.** Drop the new file under `flexlog/static/vendor/` → `python scripts/regen_vendor_integrity.py` → commit the file + `INTEGRITY.txt` + `flexlog/web/vendor_integrity.py` together. `make install` verifies the manifest.
- **Route changes need an `docs/openapi.yaml` change in the same commit.** The drift tests will fail otherwise. `make openapi` runs the validator + drift checks for quick feedback. Deprecating a route means `deprecated: true` + `x-removal-version: "X.Y.Z"`.

## Useful pointers

- **PRD:** `docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md` — the canonical product spec the codebase was built against.
- **Per-feature design specs + implementation plans:** `docs/superpowers/specs/*` and `docs/superpowers/plans/*` (gitignored, local-only). Recent specs: link-thumbnails (v0.7.0), status-bar + data-integrity cleanup (v0.8.0), supply-chain defenses (v0.8.2). Each pairs with a plan that the subagent-driven-development workflow executed.
- **`FLEXLOG_DEBUG=1`** enables Flask debug mode (auto-reload on file changes). Don't enable it when serving real data — debug pages leak too much.
- **`/superpowers:brainstorming`** is the user's preferred entry point for designing new features. It produces a spec, then `/superpowers:writing-plans` produces an implementation plan, then `/superpowers:subagent-driven-development` executes it task-by-task with two-stage review (spec compliance + code quality) per task.
- **Release log:** the README has a section per shipped version (v0.7.0 paste-link-thumbnails, v0.8.0 status bar + durability, v0.8.2 supply-chain hardening + bundled M1-M5 pentest fixes). Tags exist for each released version; v0.8.1 was deliberately skipped — those security fixes were bundled into v0.8.2.
