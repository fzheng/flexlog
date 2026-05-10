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
- Per-link thumbnails on session links
- Media Library at `/library` with type filters, orphans-only filter,
  and hard-delete (the only place that removes a file from disk)
- Live config reload — edit `config.json`, click Reload on `/settings`,
  no restart
- **Auth + fake landing page:** the URL displays a Google-clone search
  box to anyone unauthenticated; type the admin password to enter,
  anything else 303-redirects to a real Google search of that term.
  Sessions auto-expire after 30 minutes of inactivity, on server
  restart, or when you click Logout
- Friendly 404 / 413 / 500 error pages, skip-to-content link, all form
  inputs labelled

## Quick start

```bash
git clone git@github.com:fzheng/flexlog.git
cd flexlog
make install                                  # creates .venv, installs flexlog
make hash-password                            # prompt for admin password,
                                              # prints SHA-512 hex line
mkdir -p flexlog-data
echo 'FLEXLOG_ADMIN_PASSWORD_SHA512=<paste-the-hex>' > flexlog-data/.env
chmod 600 flexlog-data/.env
make run                                      # http://127.0.0.1:5050/
```

Visiting `/` shows the fake landing page. Type the password to enter the
real app. Override the data directory or port:

```bash
make run DATA_DIR=$HOME/flexlog-data PORT=5151
```

Requires Python 3.11+. If your default `python3` is older, pass
`PYTHON=python3.13` (or whichever) to `make install`.

## Privacy & data

- **Single-user, local-only.** No accounts, no roles, no multi-user.
  This is by design — the data model assumes one owner.
- **All state in one directory.** `$FLEXLOG_DATA_DIR/` holds the SQLite
  database, the secret key, the admin password hash, all uploaded media
  files, and `config.json`. Nothing else.
- **Backup is copy.** Stop the app, `tar czf backup.tar.gz $FLEXLOG_DATA_DIR/`,
  done. To restore, drop the directory on another machine, point
  `FLEXLOG_DATA_DIR` at it, run `flexlog`.
- **The fake landing page hides the URL,** but doesn't harden the app
  for hostile public exposure. There's no rate limiting, no lockout, no
  abuse protection beyond a strong SHA-512 password. If you put this on
  the open internet, put a reverse proxy with rate limiting in front,
  use a long random password, and consider whether single-user
  local-first is the right tool for your situation at all.

## For developers

```bash
make test       # full pytest suite, 85% coverage gate enforced
make test-cov   # same, plus term-missing coverage report
make smoke      # boot + dashboard fetch against a temp dir, then teardown
make help       # all targets
```

The codebase grew via five development milestones (foundation → people
→ sessions → media → polish) plus post-MVP features (runtime config
reload, auth + fake landing). The product spec is
`docs/1v1_Journal_PRD_Engineering_Ready_v3_File_Based_DB.md`. Per-feature
specs and plans live under `docs/superpowers/` locally — that directory
is gitignored, so it stays out of the public repo.

`FLEXLOG_DEBUG=1` enables Flask debug mode (auto-reload on file changes).
Don't enable it when serving real data.
