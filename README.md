# flexlog

A local-first, single-user web app for recording recurring 1-on-1 sessions
with people you interview, survey, poll, or talk to regularly. The same
codebase covers job interviews, journalist interviews, polls, school
surveys, coaching journals, language exchange logs — anything that's a
person, a date, some notes, maybe some media, repeated.

Privacy by default: no cloud, no accounts, no telemetry, no third-party
network requests. Your SQLite database, photos, audio, video, secret key
and admin password hash all live in a single local directory you back up
by copying.

## Use cases

flexlog ships with the labels of an "Interview Log" but every user-facing
string is in `config.json`. Rename the entity, the session, the rating
dimensions, the search placeholder — the same code becomes:

- **Job interviews:** track candidates across rounds, score on rubrics
  you define, attach a voice memo of the conversation, search by tag
  ("backend", "senior", "remote-only").
- **Journalist interviews:** keep sources organized by beat, audio-record
  inline, link out to the published piece, attach reference photos.
- **Polls:** one "respondent" per row, custom rating dimensions for each
  question, dashboard sort by averaged answer.
- **School surveys:** students as the entity, periodic check-ins as
  sessions, custom dimensions for whatever you track (engagement,
  understanding, sentiment).
- **Coaching, language exchange, peer reviews, mentoring:** anything
  recurring 1-on-1 that benefits from a date-stamped, searchable log
  with media + rating dimensions.

### Worked example: journalist interviews

Edit `$FLEXLOG_DATA_DIR/config.json`:

```json
{
  "app": {
    "name": "Source Log",
    "entity_singular": "Source",
    "entity_plural": "Sources",
    "session_singular": "Interview",
    "session_plural": "Interviews"
  },
  "ratings": [
    {"id": "candor", "label": "Candor", "description": "How forthcoming the source was", "scale_min": 1, "scale_max": 5, "enabled": true},
    {"id": "depth",  "label": "Depth",  "description": "Substance of the material", "scale_min": 1, "scale_max": 5, "enabled": true}
  ],
  "ui_strings": {
    "new_person": "Add Source",
    "add_session": "Log Interview",
    "search_placeholder": "Search sources or beats",
    "empty_dashboard": "No sources yet. Add your first source to begin."
  }
}
```

Save, visit `/settings`, click **Reload now** — the new labels appear
across the dashboard, person detail, session form, and Media Library
without restarting the app.

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

## Features

- People with global tags; dashboard with search + sort (alphabetical,
  last session, total sessions, average score, any custom rating dimension)
- Avatar cropper — upload an image, circular crop client-side, replace
  freely (the previous avatar becomes a Media Library orphan)
- Sessions with date, custom rating dimensions, free-form notes, links
- Media uploads per session: multiple photos, audio files, videos.
  SHA-256 deduplication means the same file uploaded twice produces one
  file on disk and one row in the database
- Inline playback: HTML5 `<audio>` and `<video>` players for audio/video,
  PhotoSwipe lightbox carousel for photos
- **Paste-your-own link thumbnails** — focus a link row, ⌘V / Ctrl+V a
  screenshot (or drop an image); the thumbnail uploads through the
  encrypted media pipeline and shows in the link list. Click to open
  full-size in a PhotoSwipe lightbox.
- **Status bar** at the bottom of every authed page shows total data
  dir size and last session save timestamp — at-a-glance journaling
  cadence without leaving the page.
- Media Library at `/library` with type filters, orphans-only filter,
  and hard-delete (the only place that removes a file from disk).
  Hard-delete refuses if any reference still exists — surfaces a clear
  "still in use" error rather than silently cascading the delete.
- Live config reload — edit `config.json`, click Reload on `/settings`,
  no restart
- **Auth + fake landing page:** the URL displays a Google-clone search
  box to anyone unauthenticated; type the admin password to enter,
  anything else 303-redirects to a real Google search of that term.
  Sessions auto-expire after 30 minutes of inactivity, on server
  restart, or when you click Logout. Logout drops the master key from
  memory and disposes the encrypted DB engine.
- **Hardened browser surface** — strict CSP (`script-src 'self'`,
  `connect-src 'self'`, `frame-ancestors 'none'`), Subresource
  Integrity on every vendored `<script>`/`<link>`, secure session
  cookie flags.
- Friendly 404 / 413 / 500 error pages, skip-to-content link, all form
  inputs labelled

## Quick start

```bash
git clone git@github.com:fzheng/flexlog.git
cd flexlog
make install                                  # creates .venv, installs flexlog
make run                                      # http://127.0.0.1:5050/
```

On first run, visit `http://127.0.0.1:5050/` in a browser. flexlog detects
that no password is configured yet and shows a **Set Admin Password** form
(not the Google clone). Pick a password of at least 8 characters — it's
used to log in AND to unlock the encrypted database. Once set, every
visit shows the fake Google landing; type your password into the search
box to log in. Type anything else and the page 303-redirects to a real
Google search of that term.

**There is no password recovery.** Forgotten password = lost data.
flexlog never stores the plaintext password and the master encryption
key is wrapped under a KEK derived from it. Choose carefully and keep a
backup.

To change your password later, visit `/settings` and use the **Change
password** form. The change is constant-time (it re-wraps the master
key with a new KEK) and doesn't touch any user data on disk.

Override the data directory or port:

```bash
make run DATA_DIR=$HOME/flexlog-data PORT=5151
```

Requires Python 3.11+. If your default `python3` is older, pass
`PYTHON=python3.13` (or whichever) to `make install`.

## Privacy & data

- **Single-user, local-only.** No accounts, no roles, no multi-user.
  This is by design — the data model assumes one owner.
- **All state in one directory.** `$FLEXLOG_DATA_DIR/` holds the
  encrypted SQLCipher database, the Flask secret key (for CSRF +
  session signing — not user data), `kdf_params.json` (Argon2id salt +
  the wrapped master key — useless without your password), all
  encrypted media files, and `config.json`. Nothing else.
- **Encryption at rest.** Every byte of user data on disk is encrypted.
  The SQLite DB uses SQLCipher (AES-256 + HMAC-SHA512 per page); media
  files use chunked AES-GCM (64 KB chunks, deterministic per-file FEK).
  The encryption keys live only in process memory after you log in;
  server restart drops them and forces a re-login.
- **Backup is copy.** Stop the app, `tar czf backup.tar.gz $FLEXLOG_DATA_DIR/`,
  done. To restore, drop the directory on another machine, point
  `FLEXLOG_DATA_DIR` at it, run `flexlog`.
- **The fake landing page hides the URL,** but doesn't harden the app
  for hostile public exposure. There's no rate limiting, no lockout, no
  abuse protection beyond Argon2id KDF cost. If you put this on
  the open internet, put a reverse proxy with rate limiting in front,
  use a long random password, and consider whether single-user
  local-first is the right tool for your situation at all.

## For developers

```bash
make test       # full pytest suite, 85% coverage gate enforced
make test-cov   # same, plus term-missing coverage report
make smoke      # boot + dashboard fetch against a temp dir, then teardown
make lock       # regenerate requirements.lock (run after dep bumps)
make audit      # pip-audit --strict against the lock (release gate)
make openapi    # validate docs/openapi.yaml + run drift tests
make help       # all targets
```

`docs/openapi.yaml` is the canonical HTTP API spec — every Flask route
documented with parameters, request bodies, response codes, and auth
requirements. The spec is drift-tested: adding a route requires adding
it to the spec in the same commit; the test suite fails on any mismatch
between the spec and `app.url_map`. Useful for understanding the API
surface, planning deprecations (mark `deprecated: true` + add
`x-removal-version`), or generating client code via standard OpenAPI
tooling.

`make install` enforces dep integrity end-to-end:

1. `pip install --require-hashes -r requirements.lock` — refuses any
   package whose downloaded bytes don't match the recorded sha256.
2. `sha256sum -c flexlog/static/vendor/INTEGRITY.txt` (or `shasum -a 256
   -c` on macOS) — refuses if any vendored JS/CSS file on disk has
   drifted from the committed manifest.

After bumping a dep in `pyproject.toml`, run `make lock && make audit`
and commit `requirements.lock` alongside. After updating a vendored
JS/CSS asset, run `python scripts/regen_vendor_integrity.py` and
commit the file change together with the regenerated `INTEGRITY.txt`
and `flexlog/web/vendor_integrity.py`.

The codebase grew via five development milestones (foundation → people
→ sessions → media → polish) plus post-MVP features (runtime config
reload, auth + fake landing, paste link thumbnails, status bar,
supply-chain hardening). The product spec is
`docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md`. Per-feature
specs and plans live under `docs/superpowers/` locally — that directory
is gitignored, so it stays out of the public repo.

`FLEXLOG_DEBUG=1` enables Flask debug mode (auto-reload on file changes).
Don't enable it when serving real data.
