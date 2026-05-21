# Changelog

Release notes for flexlog. Newest first. Each section describes the
shipped functionality, breaking changes (if any), and migration notes.

## v1.0.0 — Cloud Deployment (Railway)

flexlog is now deployable to [Railway](https://railway.com) as a
single-user cloud journal, accessible from any browser.

- **`flexlog/storage/` abstraction.** New `StorageBackend` protocol
  with `LocalStorage` (dev / tests) and `S3Storage` (production)
  implementations. `MirroredStorage` wraps two backends with sync
  replication + rollback-on-failure semantics.
- **Two-bucket redundancy.** Media files live in `flexlog-media`
  (primary) and are sync-replicated to `flexlog-backups` (replica
  + DB snapshots) for full data durability — losing one bucket is
  fully recoverable from the other.
- **Post-commit DB backups.** A background worker snapshots the
  SQLCipher DB via `sqlite3_backup` on every commit, uploads to
  `flexlog-backups` under `db/db-<ISO>.db`, and rotates to keep
  only the 30 most recent. Cold-boot restore on container start
  if the Volume's DB is missing.
- **Auth hardened for public exposure.** ProxyFix for Railway's
  single proxy hop, HSTS + Secure cookies when `FLEXLOG_BEHIND_TLS=1`,
  noindex meta + /robots.txt. Argon2id KDF cost (~500ms per attempt)
  is the brute-force defense; no application-level rate limiting
  (single-user app + the KDF cost makes additional rate limiting
  more pain than protection).
- **Docker + railway.json.** One-command deploy. Gunicorn in
  single-worker mode (SQLCipher doesn't multi-process well) with
  4 threads for concurrent reads.
- **DR tooling.** `scripts/restore_media_from_backup.py` rebuilds
  the primary bucket from the backup bucket in disaster scenarios.

See [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) for the Railway walkthrough.
~$5-6/month for a single-user deployment.

For local development (no S3, no Volume), nothing changes — the
default storage backend is still `LocalStorage` and `make run`
works as before.

## v0.9.0 — OpenAPI Contract + Coverage Sweep + Pre-Release Fixes

- **OpenAPI 3.0 spec.** `docs/openapi.yaml` documents every Flask
  route (34 operations across 11 blueprints) with parameters, request
  bodies, response codes, and auth requirements. Render with any
  OpenAPI viewer (Swagger UI / ReDoc), generate client SDKs via
  `openapi-generator`, or just read it as the canonical HTTP API
  contract.
- **Drift detection (15 tests).** `tests/integration/test_openapi.py`
  walks `app.url_map` and the spec in both directions, failing on any
  route added without docs, removed but spec-stale, method changed,
  or auth annotation drift. The runtime `ALLOWED_UNAUTH_ENDPOINTS`
  set must match the spec's `security: []` operations exactly.
- **Deprecation workflow.** Mark an operation `deprecated: true`
  with `x-removal-version: "X.Y.Z"`; the drift test enforces the
  removal-version pairing so deprecations don't disappear silently.
- **Pre-release cleanup.** Fixed 4 spec/runtime drift bugs the review
  surfaced: `/logout` now correctly marked public; oversize uploads
  return 413 via a new `PayloadTooLargeError` subclass while other
  validation failures correctly return 422; `orphan_delete_media_file`
  now checks `SessionLink.thumbnail_media_id` references (was missing
  since v0.7.0); `/dashboard` sort parameter enum matches the
  handler's actual accepted values.
- **+58 coverage tests.** 738 → 813 total, coverage 94.21% → 96.36%.
  New tests cover crypto header validation, kdf_params corruption
  paths, status-bar malformed-data handling, upload endpoint error
  branches, media Range header edge cases, db engine lifecycle,
  setup-state redirects, change-password error paths, and the
  PersonForm whitespace-only-alias validator.
- **`make openapi` target** validates the spec + runs drift tests
  in ~0.4 s, separate from the full `make test` suite. New `make help`
  output lists the maintainer-only targets (`lock`, `audit`,
  `openapi`) explicitly.
- **Stale docstring sweep.** `db/__init__.py` (NullPool not
  SingletonThreadPool; `register_db_teardown` not `attach_to_app`),
  `services/media.py` (audio/video magic-byte check added in v0.8.2 M4),
  `services/library.py` (refuse-on-reference, not silent cascade),
  `services/status.py` (context processor lives in `app.py`),
  `crypto.py` (chunked format is in this module, not "a later step")
  all corrected. `build_header` / `parse_header` got docstrings
  explaining the binary layout + error contract.

## v0.8.2 — Supply-Chain Hardening + Pentest Fixes

### Supply-chain defenses

- **Hash-pinned dependency lock.** `requirements.lock` lists every
  direct + transitive Python dep with its SHA-256 hash. A hijacked
  PyPI version fails `pip install --require-hashes` and the install
  refuses to continue. Regenerate after dep changes via `make lock`.
- **CVE audit via `make audit`.** Runs `pip-audit --strict` against
  the lockfile and exits non-zero on any known vulnerability —
  intended as a release gate. Requires outbound network (OSV DB);
  the running app still makes zero third-party requests.
- **Vendored-JS integrity manifest.** `flexlog/static/vendor/INTEGRITY.txt`
  is a SHA-256 manifest of every committed PhotoSwipe / Cropper.js
  file. `make install` runs `sha256sum -c` (or `shasum -a 256 -c` on
  macOS) and aborts if any vendor file has drifted on disk.
- **Subresource Integrity (SRI) in templates.** Every `<script>`
  and `<link rel="stylesheet">` for a vendored asset now carries an
  `integrity="sha384-..."` attribute. The browser refuses to execute
  a tampered file even if it slips past the server.
- **Strict response headers.** CSP (`script-src 'self'`,
  `connect-src 'self'`, `frame-ancestors 'none'`), `X-Frame-Options:
  DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  no-referrer`, `Permissions-Policy` denying all hardware APIs.
  Inline event handlers in templates were migrated to data-attribute
  hooks in `static/js/csp_handlers.js` so the CSP doesn't silently
  break delete-confirmation dialogs.

### Bundled pentest fixes

A round of pentest-driven hardening shipped in the same release (these
were committed but never tagged separately as v0.8.1):

- **Long-passphrase leak fixed.** `_looks_like_password` no longer
  caps at 64 characters — a 65+ char passphrase mis-typed at the
  fake-Google landing no longer ends up in `google.com/search?q=...`.
- **Session cookie flags.** `HttpOnly`, `SameSite=Lax` explicitly
  set; defensible if anyone ever puts the app behind a reverse proxy.
- **Constant-time master-key compare.** `change_password` uses
  `hmac.compare_digest`.
- **HEIC decompression-bomb cap.** Rejects HEIC images claiming
  `width × height > 50M` pixels BEFORE Pillow allocates the decoded
  bitmap.
- **Audio/video magic-byte check.** Rejects polyglot files (HTML/PHP
  shaped payload with bogus declared audio/mp4 MIME).

### Maintainer notes

To regenerate the vendor integrity manifest after updating a
vendored file, run `python scripts/regen_vendor_integrity.py` and
commit the resulting `INTEGRITY.txt` + `flexlog/web/vendor_integrity.py`.
After bumping a Python dep, run `make lock && make audit` and commit
the updated `requirements.lock` alongside `pyproject.toml`.

## v0.8.0 — Status Bar + Data-Integrity Sweep

- **Status bar at the bottom of every authed page.** Shows total
  `$FLEXLOG_DATA_DIR/` size and the timestamp of the most recent
  session save. Cheap: one SQL query + one filesystem walk per
  render. Hidden when unauthed.
- **Durability fixes (7 items).** Encrypted media writes now fsync
  before close. Upload failures unlink their encrypted target
  instead of leaking it as an orphan. Concurrent identical-bytes
  uploads no longer raise IntegrityError to the user — the dedup
  race resolves cleanly. Hard-delete's after-commit listener is
  shared (not per-call) and logs unlink failures instead of
  swallowing them. Tmp-uploads sweep cutoff is 24h (was 1h). The
  vestigial `auth` table created by setup is removed.

No schema change. No new dependencies.

## v0.7.0 — Link Thumbnails (paste your own screenshot)

- **Each link gets a thumbnail you paste yourself.** Click a link row in the session form to focus it, then paste (⌘V / Ctrl+V) a screenshot — or drop an image onto the row. The image uploads to the existing encrypted media pipeline; on save, the link's thumbnail is set to that MediaFile.
- **Why paste, not auto-fetch?** v0.6.0 tried headless-Chromium screenshots. Real-world pages defeated it: lazy-loaded images, paywalls, captchas, JS frameworks that need a logged-in session. Pasting is faster, gives you control, and removes ~280 MB of bundled Chromium from the install.
- **SHA-256 dedup.** Pasting the same screenshot for two different links resolves to a single MediaFile on disk.
- **Reorder or re-save freely.** The hidden `link_thumb_keys` input parallel to each URL preserves the existing thumbnail. The ✕ on the thumbnail clears it; pasting again replaces it.
- **No outbound network.** flexlog makes zero third-party requests when you save a link.

## v0.4.0 — Weighted Overall Ratings + Star Input

- **Weighted overall rating per session.** Each rating dimension now has a `weight: float` in config. The session overall is the weighted average of its sub-ratings, displayed as a 1-decimal number (e.g. `4.3 / 5`).
- **Star input.** The session form replaces number typing with star clicking. Five stars per dimension; click again to decrement (or click star 1 when at 1 to clear to 0). Keyboard: ←/→ to adjust, Space/Enter to commit. A live overall preview updates as you click.
- **Sub-ratings locked at 0..5 integer.** The `scale_min` / `scale_max` fields are removed from the config schema (`schema_version` bumps to 3).
- **Dashboard sorted by overall (avg).** New default sort: average overall across each person's sessions. Old `custom:<dim>` sorts stay for sortable dims.
- **Person detail shows the average.** Above the session list: `"Average across N interviews: 4.2"`. Each session row shows its own overall.
- **Settings Ratings tab:** scale columns gone; new weight column with live sum-of-enabled-weights indicator and a "Distribute weights evenly" button.

**No DB migration.** v0.3.0 wasn't in production yet — pre-v3 `config.json` files auto-upgrade on first launch (scale fields stripped, weights distributed uniformly). If you had any sessions stored in a v0.3.0 data dir, clear them before upgrading.

## v0.3.0 — Settings UI + session-form UX overhaul

- **Settings page** at `/settings` — five tabs (App, Ratings, UI strings, Limits, Raw JSON) replace hand-editing `config.json`.
- **Custom rating fields** — the hardcoded `overall_score` is gone. All rating dimensions are defined in config (add / rename / disable / delete / reorder). Existing data is migrated automatically on first launch.
- **Progressive media uploads** — photos / audio / video upload immediately when added, with per-file progress and remove. Save is a fast link-only operation.
- **Revamped links UI** — single URL textbox + Add. Validated client-side and server-side.
- **Session detail reorder** — Links → Ratings → Notes → Audio → Photos → Videos. Audio plays inline; the redundant Download anchor is removed.

**Migration:** runs automatically on first startup via `PRAGMA user_version`. The previous `overall_score` column is merged into a unified `ratings_json` keyed by config dimension id. No data wipe; backups remain wise before any upgrade.
