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

## Releases & deployment

- **Release notes:** see [`docs/CHANGELOG.md`](docs/CHANGELOG.md) for
  per-version notes (v1.0.0 cloud deployment back to v0.3.0).
- **Self-host on macOS (recommended for sensitive content):** see
  [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md) for the step-by-step
  walkthrough — your Mac runs flexlog; rclone backs the encrypted
  data dir to a Railway storage bucket every 15 minutes; Tailscale
  Funnel provides public HTTPS access.
- **Cloud deployment (Railway):** see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
  for the step-by-step walkthrough — Volume + two Storage Buckets,
  Dockerfile build, env vars, first-run setup, disaster recovery.
- **Recovery procedures:** see [`docs/RECOVERY.md`](docs/RECOVERY.md)
  for the four-scenario recovery runbook (lost Mac, corrupted live
  data, point-in-time rollback, catastrophic loss).

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
