# Product Requirements Document (PRD)

**Product Name:** 1v1 Journal  
**Internal Codename:** FlexLog  
**Version:** 1.0 MVP — Engineering-Ready Draft v3  
**Date:** May 2026  
**Owner:** PM  
**Status:** Ready for Engineering Review — File-Based Database Decision Added  

---

## 1. Executive Summary

1v1 Journal is a local-only, single-user web application for recording recurring one-on-one sessions with people. The app stores structured records in a single file-based SQLite database and stores media as regular files in a configured local data directory. The persistent data directory must be provided as an absolute filesystem path through an environment variable.

The key product principle is configurability. The same codebase should be re-themeable for multiple legitimate use cases, such as interview logs, coaching session logs, mentorship archives, language exchange journals, and private conversation journals, without changing application logic.

The MVP must be reliable, private, explicit about local storage paths, portable across machines, and simple enough for a non-developer owner to operate locally and customize through `config.json`.

---

## 2. Product Goals

### 2.1 Goals

1. Let a single owner create and manage a private local archive of people and recurring 1v1 sessions.
2. Support rich session records: notes, scores, custom ratings, links, audio, video, and photos.
3. Allow the owner to customize product terminology, entity labels, session labels, UI text, tags, and rating dimensions from configuration.
4. Store all structured data and media locally with no cloud dependency and no telemetry.
5. Use SQLite as the required file-based database for structured data; no external database server is required.
6. Make backup and restore possible by copying the configured local data directory and preserving the environment/configuration settings.
7. Provide a clean desktop-first UI that feels polished across supported public templates.

### 2.2 Non-Goals for MVP

1. No multi-user support.
2. No login, account creation, cloud sync, or hosted deployment requirement.
3. No mobile-first design requirement.
4. No folder/database encryption in MVP.
5. No rich text editor beyond plain textarea notes.
6. No statistics charts.
7. No PDF export in MVP.
8. No automatic external thumbnail fetching, metadata scraping, or third-party network calls.
9. No AI summarization, transcription, or media processing.
10. No external database server such as PostgreSQL, MySQL, MongoDB, or Redis.
11. No custom JSON/YAML flat-file database as the source of truth for structured records.

---

## 3. Target Users and Use Cases

### 3.1 Primary User

A single privacy-conscious owner who wants to keep a structured record of recurring 1v1 sessions with different people.

### 3.2 Supported MVP Templates

The initial public template is **Interview Log**. The app must also be configurable for the following use cases through `config.json`:

- Podcast or interview guest archive
- Personal training or private coaching session log
- Language exchange partner log
- 1v1 mentorship or career coaching archive
- Deep conversation or coffee chat journal

---

## 4. Core Product Principles

1. **Local-first:** Data and media remain on the owner’s machine.
2. **Single-user:** The app is for one trusted owner only.
3. **Configurable:** User-facing language and rating dimensions come from configuration, not hardcoded strings.
4. **Explicit storage root:** The app uses an absolute local data directory from an environment variable.
5. **File-based database:** Structured data lives in one SQLite database file under the configured data directory.
6. **Portable restore:** Backup/restore works by copying the configured data directory and updating the env var on the target machine.
7. **Simple:** Use SQLite, filesystem storage, and server-rendered or lightweight client-side UI.
8. **Private by default:** No telemetry, no third-party CDNs, no external API calls, and no automatic external fetching.

---

## 5. MVP Scope Summary

### 5.1 Included in MVP

- Dashboard showing people, not sessions
- Add, edit, view, and delete people
- Add, edit, view, and delete sessions
- Alias, avatar, tags, session notes, scores, custom ratings, links, and media
- Global tags shared across people
- Up to 6 custom rating dimensions
- Plain-text notes with full UTF-8 and Chinese support
- Multiple audio, video, and photo uploads per session
- Inline HTML5 audio/video playback
- Photo carousel and full-screen lightbox
- Avatar upload and circular cropper
- Search and sorting on dashboard
- File-based SQLite database named `encounters.db` under `$FLEXLOG_DATA_DIR/data/`
- Filesystem media storage under `$FLEXLOG_DATA_DIR/uploads/`
- Required absolute path environment variable: `FLEXLOG_DATA_DIR`
- `config.json` for labels, UI strings, rating dimensions, and basic limits
- No external database server; SQLite is the required structured-data source of truth
- Backup and restore by copying `$FLEXLOG_DATA_DIR` and preserving env/config settings

### 5.2 Deferred to Post-MVP

- PDF export of any kind, including full-app, single-person, and single-session exports
- Encryption for database and uploads
- Dark mode
- Custom color themes
- Markdown or rich text notes
- Statistics dashboard and charts
- Global timeline view
- Keyboard shortcuts
- Mobile-first responsive design
- JSON import/export backup format beyond the core SQLite/file copy backup model

---

## 6. Functional Requirements

### 6.1 Configuration and Customization

### Requirement

All major user-facing labels must be configurable through `config.json`. The application must not require Python code changes to switch from one public use case to another.

### Configurable Items

- App name
- Main entity singular/plural labels, for example `Guest` / `Guests`
- Session singular/plural labels, for example `Interview` / `Interviews`
- Button labels
- Empty states
- Field labels
- Dashboard column/card labels
- Rating dimensions
- Upload and display limits

### Config File Location

- MVP default: `$FLEXLOG_DATA_DIR/config.json`.
- The path is resolved from the absolute env-configured data directory.
- The app must fail fast with a clear error if the config file is missing or malformed.

### Rating Configuration

- MVP supports one required `overall_score` from 0 to 5.
- MVP supports up to 6 custom rating dimensions.
- Each custom rating dimension must have:
  - Stable `id`
  - Display `label`
  - Optional `description`
  - Scale minimum: 0
  - Scale maximum: 5
  - Enabled flag

### Important Engineering Constraint

Rating dimension `id` values are stable data keys. Changing a label is safe. Changing or deleting an `id` may affect historical session records. The app should not crash if historical records contain old rating IDs; it should either hide unknown ratings by default or display them under an “Archived Ratings” section.

### Example `config.json`

```json
{
  "app": {
    "name": "Interview Log",
    "entity_singular": "Guest",
    "entity_plural": "Guests",
    "session_singular": "Interview",
    "session_plural": "Interviews"
  },
  "ratings": [
    {
      "id": "overall_quality",
      "label": "Overall Quality",
      "description": "General impression of the session",
      "scale_min": 0,
      "scale_max": 5,
      "enabled": true
    },
    {
      "id": "clarity",
      "label": "Clarity",
      "description": "How clear and articulate the person was",
      "scale_min": 0,
      "scale_max": 5,
      "enabled": true
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
    "max_upload_mb_per_file": 500
  }
}
```

### Acceptance Criteria

- When the owner edits app/entity/session labels in `config.json`, the UI uses the new labels after app restart or config reload.
- The app validates `config.json` at startup and shows a clear error if required keys are missing or malformed.
- The app does not hardcode public-template wording in routes, templates, or JavaScript.
- More than 6 enabled custom rating dimensions should produce a validation warning or error.

---

### 6.2 Data Model

### Entities

#### Person

A person is the primary dashboard object.

Fields:

- `id` — UUID string recommended
- `alias` — required display name
- `avatar_file_key` — nullable file key under `$FLEXLOG_DATA_DIR/uploads/` for the cropped avatar image
- `created_at`
- `updated_at`

#### Tag

Tags are global keywords shared across all people.

Fields:

- `id`
- `name` — unique, case-insensitive display name
- `slug` — unique normalized value
- `created_at`

#### PersonTag

Many-to-many relationship between people and tags.

Fields:

- `person_id`
- `tag_id`

#### Session

A session is one meeting with one person.

Fields:

- `id` — UUID string recommended
- `person_id`
- `session_date` — required date
- `overall_score` — required 0–5 score for MVP unless explicit draft mode is added
- `custom_ratings_json` — JSON object mapping rating dimension IDs to numeric 0–5 values
- `notes` — plain text, UTF-8, supports Chinese
- `created_at`
- `updated_at`

#### SessionMedia

Media files attached to one session.

Fields:

- `id`
- `session_id`
- `media_type` — `photo`, `audio`, or `video`
- `file_key` — required file key under `$FLEXLOG_DATA_DIR/uploads/`
- `original_filename`
- `mime_type`
- `file_size_bytes`
- `sort_order`
- `created_at`

#### SessionLink

Links attached to one session.

Fields:

- `id`
- `session_id`
- `url`
- `label` — optional
- `thumbnail_file_key` — optional file key under `$FLEXLOG_DATA_DIR/uploads/` for user-uploaded thumbnail only
- `sort_order`
- `created_at`

### Acceptance Criteria

- One person can have many sessions.
- One session can have many media files and links.
- Deleting a person requires confirmation and deletes or archives the person’s sessions and associated media according to the deletion behavior defined below.
- The configurable storage path is the absolute env var `FLEXLOG_DATA_DIR`; database media records store safe file keys under that root and requests for files outside that directory are rejected.
- Structured records are stored in SQLite tables, not JSON flat files.
- The SQLite database must not store machine-specific absolute paths for media files.
- Notes persist and render correctly for Chinese text and other UTF-8 content.

---

### 6.3 Storage and Folder Structure

### Requirement

Structured data and media are stored locally under a required absolute data directory configured by environment variable. The application must not silently default to project-relative persistent storage in MVP.


### File-Based Database Decision

Use **SQLite** as the MVP file-based database. SQLite gives us the portability benefit of a single local database file while still providing transactions, indexes, relational integrity, and simple migrations.

This means:

- The source of truth for structured records is `$FLEXLOG_DATA_DIR/data/encounters.db`.
- The app does not require PostgreSQL, MySQL, MongoDB, Redis, Dockerized database services, or any background database daemon.
- The app should not implement a custom JSON, YAML, or CSV flat-file database for people, sessions, ratings, links, tags, or media records.
- `config.json` remains file-based configuration only; it is not the database.
- Media remains stored as normal files under `$FLEXLOG_DATA_DIR/uploads/`.
- SQLite records should store stable IDs and storage keys, not absolute paths that would break after moving the data directory.

### Why SQLite Instead of JSON Files

SQLite keeps the implementation simple and portable while avoiding common problems with hand-rolled file databases:

- safer writes through transactions
- easier schema validation and migrations
- indexed search and sorting for dashboard performance
- many-to-many tags without duplicating data
- reliable delete/update behavior across people, sessions, links, ratings, and media
- lower risk of corrupting the entire dataset when one write fails

JSON export/import can be considered post-MVP, but the MVP persistence layer should remain SQLite plus filesystem media.

### Required Environment Variable

The app must read the persistent storage directory from:

```bash
FLEXLOG_DATA_DIR=/absolute/path/to/flexlog-data
```

Rules:

- `FLEXLOG_DATA_DIR` is required in MVP.
- The value must be an absolute filesystem path.
- Startup must fail fast with a clear error if the variable is missing, empty, relative, unreadable, or not writable.
- The configured directory may live outside the source-code project directory.
- The app should never assume persistent files live beside the application code.

### Required Files and Folders

Recommended persistent data structure:

```text
$FLEXLOG_DATA_DIR/
  config.json
  data/
    encounters.db
  uploads/
    <person_id>/
      avatar/
        avatar.<ext>
      <session_id>/
        photos/
        audio/
        videos/
        link_thumbnails/
```

Source-code files such as `app/`, `static/`, and `templates/` remain in the application project directory and are not part of the persistent data directory unless the owner deliberately chooses the same parent folder.

### Storage Rules

- SQLite database path: `$FLEXLOG_DATA_DIR/data/encounters.db`. This is a regular local file and the required source of truth for structured data.
- Config file path: `$FLEXLOG_DATA_DIR/config.json`.
- Media root: `$FLEXLOG_DATA_DIR/uploads/`.
- The app must create missing `data/` and `uploads/` folders under `$FLEXLOG_DATA_DIR` at startup.
- Database media references should be stored as safe file keys under `uploads/`, while the configurable storage path itself is the absolute env var `FLEXLOG_DATA_DIR`.
- Database records must not store absolute filesystem paths for avatars, photos, audio, videos, thumbnails, or other media.
- SQLite journaling should be configured with portability in mind. For MVP, prefer the default rollback-journal mode or require the app to be stopped before manual folder copy. If WAL mode is used, backup instructions must include the `encounters.db-wal` and `encounters.db-shm` files or use the SQLite backup API.
- Filenames saved to disk must be sanitized and unique.
- The original filename should be preserved in the database for display purposes.
- The app must reject or normalize any path that attempts to escape `$FLEXLOG_DATA_DIR`.
- No database or media files should be written into the application source tree unless the owner explicitly sets `FLEXLOG_DATA_DIR` there as an absolute path.

### Backup and Restore Acceptance Criteria

- Backup consists of copying the complete `$FLEXLOG_DATA_DIR` directory plus preserving environment/configuration settings.
- Manual file-copy backup should be performed while the app is stopped, or through a future app-provided backup command that uses SQLite's backup mechanism.
- Restore consists of placing that data directory on the target machine, setting `FLEXLOG_DATA_DIR` to its new absolute path, and running the app.
- People, sessions, notes, links, avatars, configuration, and media remain valid after restore.
- No external services, cloud storage, or project-relative assumptions are required for restore.

---

### 6.4 Security and Privacy

### Requirement

The app is local-only and single-user. There must be no telemetry, cloud sync, account system, or external API dependency.

### MVP Security Requirements

- The local web server binds to `127.0.0.1` by default, not `0.0.0.0`.
- Debug mode must be off in production/local-run mode.
- No third-party CDN scripts, fonts, CSS, analytics, or tracking pixels.
- All static assets must be served locally.
- The app must not automatically fetch external website metadata or thumbnails.
- User-added links may open in a new browser tab only after explicit user click.
- External links must use `target="_blank"` and `rel="noopener noreferrer"`.
- Uploaded files must be validated by extension and MIME type.
- Upload size limits must be enforced.
- Uploaded filenames must be sanitized to prevent path traversal.
- Serving media must not allow access outside `$FLEXLOG_DATA_DIR/uploads/`.
- User-entered notes, labels, aliases, tags, and links must be escaped to prevent XSS.
- Forms that mutate data should include CSRF protection or an equivalent local-app protection mechanism.

### Network Behavior

The app itself must make zero external network calls. Opening a user-entered link in the browser is allowed only as a user-initiated action.

### Post-MVP Security

- Password-based encryption for database and uploads.
- Clear lock/unlock UX.
- Recovery warning that lost passwords cannot be recovered.

### Acceptance Criteria

- App startup and normal usage work without internet access.
- Browser developer tools show no third-party network requests during app usage.
- Uploaded malicious filenames such as `../../file.txt` cannot write outside `$FLEXLOG_DATA_DIR/uploads/`.
- HTML or script content entered into notes or aliases is displayed safely and not executed.

---

### 6.5 Dashboard

### Requirement

The dashboard shows a list or grid of people, not individual sessions.

### Required Elements

Each person card/list row shows:

- Circular avatar or default avatar placeholder
- Alias
- Tags
- Last session date
- Total session count
- Average overall score
- Optional average custom rating values if selected for sorting/display

### Actions

- New Person
- Search
- Sort
- Open person detail

### Search

Search must match:

- Alias
- Tag name

Search should be case-insensitive. Partial matching is acceptable.

### Sort Options

- Last session date, newest first
- Total sessions, highest first
- Average overall score, highest first
- Custom rating dimension averages, highest first
- Alias alphabetical

### Empty State

If no people exist, show configurable empty-state copy and a New Person action.

### Acceptance Criteria

- Dashboard loads successfully with 0 people, 300 people, and 3000 sessions.
- Search by alias and tag returns expected people.
- Sorting by last session, total sessions, average overall score, and enabled custom dimensions works.
- People with no sessions are handled gracefully in sorting and display.

---

### 6.6 Person Detail Page

### Requirement

The person detail page shows one person’s profile and all historical sessions.

### Required Elements

- Large circular avatar
- Alias
- Tags
- Summary statistics:
  - Total sessions
  - Last session date
  - Average overall score
  - Average custom rating dimensions where available
- Add New Session button
- Edit Person button
- Delete Person button
- Chronological session list, most recent first

### Session List Item

Each session list item shows:

- Session date
- Overall score
- Custom rating summary if configured
- Notes preview
- Media indicators, for example photo/audio/video counts
- Link count

### Acceptance Criteria

- Clicking a session opens its session detail page.
- People with no sessions show a clear empty state.
- Deleting a person requires explicit confirmation.

---

### 6.7 Add/Edit Person

### Requirement

The owner can create and edit people.

### Fields

- Alias — required
- Avatar upload — optional
- Tags — optional, global reusable chips

### Avatar Cropper

- Owner uploads one image.
- UI shows a circular cropper similar to standard profile picture upload flows.
- Owner can adjust crop area.
- Cropped image is saved and used across dashboard and detail pages.
- Only one active avatar per person.
- Replacing avatar deletes or archives the previous avatar file.

### Validation

- Alias cannot be empty.
- Avatar file must be a supported image type.
- Duplicate tag names should resolve to existing global tag.

### Acceptance Criteria

- A person can be created with alias only.
- A person can be created with alias, avatar, and tags.
- Cropped avatar appears consistently across dashboard and person detail.
- Editing tags updates dashboard search results.

---

### 6.8 Session Detail Page

### Requirement

The session detail page displays all content for one session without requiring the owner to leave the page.

### Required Sections

- Header with person alias and session date
- Overall score
- Custom ratings
- Notes
- Audio files with HTML5 players
- Video files with HTML5 players
- Photos in carousel/slideshow
- Full-screen photo lightbox
- Web links
- Edit Session action
- Delete Session action
- Back navigation to Person Detail

### Links

- Display label if provided; otherwise display URL.
- Open in a new tab.
- Optional thumbnail must be user-uploaded only.
- Do not fetch website thumbnails automatically.

### Acceptance Criteria

- Audio plays inline on the session detail page.
- Video plays inline on the session detail page.
- Photo carousel works with 1 photo and many photos.
- Lightbox opens and closes reliably.
- Links open in a new tab without navigating away from the app.

---

### 6.9 Add/Edit Session

### Requirement

The owner can create and edit sessions for a person.

### Fields

- Session date — required
- Overall 0–5 score — required unless engineering implements explicit draft mode
- Dynamic custom rating dimensions from `config.json`
- Notes textarea
- Multiple photo uploads
- Multiple audio uploads
- Multiple video uploads
- Link manager with URL, optional label, and optional user-uploaded thumbnail

### Upload Behavior

- Live preview before save is required for photos.
- Audio/video file names should be shown before save; inline preview is preferred if simple.
- Multiple files can be uploaded at once.
- Existing media can be removed during edit.
- New uploads should not delete existing media unless explicitly removed.

### Supported File Types

Engineering should define the exact allowlist, but MVP should support at minimum:

- Photos: JPEG, PNG, WebP
- Audio: MP3, WAV, M4A
- Video: MP4, WebM, MOV if browser playback is supported or graceful fallback is provided

### Acceptance Criteria

- Adding a session with only required fields succeeds.
- Adding a session with notes, ratings, links, photos, audio, and video succeeds.
- Editing a session preserves existing media unless removed.
- Deleted media no longer appears and its file is removed from disk or moved to a trash/archive folder.
- Chinese notes save and display correctly.

---

### 6.10 Delete Behavior

### Requirement

Destructive actions must require confirmation.

### MVP Behavior

- Delete Session:
  - Requires confirmation.
  - Deletes session row, links, media records, and associated media files.
- Delete Person:
  - Requires stronger confirmation because it deletes all sessions and media for that person.
  - Recommended confirmation text: type the person alias or click a second confirmation button.
  - Deletes person, person-tag relationships, sessions, links, media records, avatar, and associated media files.
- Delete Tag:
  - Removing a tag from a person does not delete the global tag unless no longer used and owner explicitly deletes it.

### Acceptance Criteria

- Accidental single-click deletion is not possible.
- Deleting a session removes it from person history and dashboard aggregates.
- Deleting a person removes them from dashboard and search.

---

### 6.11 Export Behavior

PDF export is not included in MVP. The MVP should focus on reliable local capture, editing, media playback, search, sorting, configuration, and backup/restore.

### Deferred Export Scope

Post-MVP export work may include:

- Full-app PDF export
- Single-person PDF export
- Single-session PDF export
- Optional photo thumbnails with size limits
- Audio/video represented by filenames and local paths rather than embedded playback
- Export labels that follow current `config.json` terminology

### Acceptance Criteria

- No PDF export route, button, or background dependency is required for MVP.
- MVP implementation should not introduce PDF-specific libraries unless engineering chooses to prepare a clearly isolated post-MVP module.

---

## 7. Recommended MVP Routes

Engineering may adjust route names, but the app should support these page-level flows.

```text
GET  /                          Dashboard
GET  /people/new                Add Person form
POST /people                    Create Person
GET  /people/<person_id>        Person Detail
GET  /people/<person_id>/edit   Edit Person form
POST /people/<person_id>        Update Person
POST /people/<person_id>/delete Delete Person

GET  /people/<person_id>/sessions/new   Add Session form
POST /people/<person_id>/sessions       Create Session
GET  /sessions/<session_id>             Session Detail
GET  /sessions/<session_id>/edit        Edit Session form
POST /sessions/<session_id>             Update Session
POST /sessions/<session_id>/delete      Delete Session

POST /media/<media_id>/delete           Delete individual media file
```

No export routes are required for MVP.

---

## 8. Recommended Technical Architecture

### Stack Recommendation

- Python web app
- Flask or FastAPI; PM recommendation for MVP: Flask for simple local server-rendered pages
- SQLite file database
- SQLAlchemy or direct SQLite layer with lightweight migrations
- Jinja/server-rendered templates plus lightweight JavaScript for cropper, carousel, lightbox, and upload previews
- Local static assets only

### Engineering Constraints

- App must run locally without internet.
- App should be easy to launch with a simple command or script.
- App must require `FLEXLOG_DATA_DIR` as an absolute path before startup completes.
- App should automatically create required child folders and the SQLite database file under `$FLEXLOG_DATA_DIR` if missing.
- App should include lightweight migration support for future schema changes.
- App must not require or initialize an external database server.
- App must not store structured records in ad hoc JSON/YAML files, except `config.json` for configuration.
- App should handle at least 300 people and 3000 sessions comfortably.

---

## 9. UI and UX Requirements

### Visual Direction

- Clean, professional, desktop-first interface
- Avatar-forward dashboard
- Large readable notes area
- Clear media sections
- Low clutter
- Configured terminology should appear natural throughout the UI

### Accessibility Basics

- Forms should have labels.
- Buttons should have clear names.
- Images should include alt text where appropriate.
- Keyboard navigation should work for core forms.
- Lightbox and modals should have close controls.

### Responsiveness

Desktop-first is acceptable. The app should not break on tablet-sized screens, but mobile-first polish is post-MVP.

---

## 10. Performance Requirements

The app should comfortably support:

- 300+ people
- 3000+ sessions
- 50 photos per session
- Multiple audio/video files per session, subject to local disk and browser performance

### Acceptance Criteria

- Dashboard remains usable with 300 people.
- Person detail remains usable with 100+ sessions for one person.
- Sorting and searching return results without noticeable delay on target scale.
- Large media files do not block page rendering unnecessarily; use native browser loading behavior where possible.

---

## 11. Implementation Priorities

### P0 — Must Have

- Local-only app with file-based SQLite and uploads folder under `$FLEXLOG_DATA_DIR`
- Required absolute `FLEXLOG_DATA_DIR` environment variable
- Config loading and validation from `$FLEXLOG_DATA_DIR/config.json`
- Person CRUD
- Session CRUD
- Tags
- Overall score and custom ratings
- Notes with UTF-8/Chinese support
- Media upload, storage, display, and deletion
- Avatar upload and circular cropper
- Dashboard search and sort
- Person detail with session history
- Session detail with inline media
- Backup/restore by copying `$FLEXLOG_DATA_DIR` and preserving env/config settings
- Basic security/privacy protections

### P1 — Should Have

- User-uploaded link thumbnails
- Better drag-and-drop uploads
- Better empty states
- Graceful archived-ratings display
- Basic migration command

### P2 — Nice to Have

- Tablet polish
- Media reorder controls
- Duplicate media detection
- Import/export JSON backup
- PDF export scopes

---

## 12. QA Checklist

Engineering and QA should verify:

1. App works with no internet connection.
2. No third-party network requests are made during normal usage.
3. Startup fails clearly if `FLEXLOG_DATA_DIR` is missing, relative, unreadable, or not writable.
4. Startup succeeds when `FLEXLOG_DATA_DIR` is set to a valid absolute path.
5. Owner can create, edit, and delete a person.
6. Owner can upload and crop avatar.
7. Owner can create, edit, and delete a session.
8. Owner can add Chinese notes and they display correctly.
9. Owner can upload multiple photos, audio files, and videos.
10. Audio and video play inline.
11. Photo carousel and lightbox work.
12. Owner can add multiple links with optional labels.
13. Links open in a new tab.
14. Dashboard search works by alias and tag.
15. Dashboard sorting works for all MVP sort options.
16. Config label changes appear throughout the UI.
17. Invalid config produces a clear error.
18. Copying `$FLEXLOG_DATA_DIR` to another machine while the app is stopped, updating the env var to the new absolute path, and running the app preserves all data and media references.
19. Path traversal attempts in upload filenames fail safely.
20. Script injection attempts in notes, tags, aliases, and labels do not execute.
21. No PDF export route, button, or dependency is required for MVP.
22. App handles 300 people and 3000 sessions at acceptable speed.
23. The app runs without PostgreSQL, MySQL, MongoDB, Redis, Docker, or any external database service.
24. The SQLite database stores media references as portable storage keys, not absolute machine-specific paths.

---

## 13. Open Questions for Product/Engineering Before Build

1. Should `overall_score` be required for every saved session, or should sessions be allowed as drafts with no score?
2. Should delete permanently remove media files immediately, or move them to a local trash/archive folder first?
3. Should configuration changes be applied only at app restart, or should there be a runtime reload button?
4. Should the initial implementation use UUIDs for portability and file paths, or integer IDs for simplicity?
5. Should SQLite use the default rollback journal for easier manual copying, or WAL mode with a documented backup command?

Recommended PM defaults:

- `overall_score` is required in MVP.
- Deletes are permanent after confirmation.
- Config changes apply after app restart.
- Use UUID strings for IDs to avoid path collision and simplify media folder naming.
- Use SQLite default rollback-journal mode for MVP unless engineering provides a reliable backup command that handles WAL safely.

---

## 14. Locked Decisions

1. Initial public template: Interview Log.
2. MVP supports a maximum of 6 enabled custom rating dimensions.
3. Tags are global and shared across all people.
4. Avatar cropper uses a standard circular profile-picture crop pattern.
5. App is single-user and local-only.
6. Encryption is post-MVP.
7. Automatic external thumbnail fetching is not allowed in MVP because it conflicts with the zero-network privacy requirement.
8. Persistent storage root must come from required absolute env var `FLEXLOG_DATA_DIR`.
9. PDF export is not included in MVP.
10. SQLite is the required file-based MVP database.
11. Do not use an external database server or a hand-rolled JSON/YAML database for MVP structured records.
12. Database rows must store portable storage keys for media, not absolute filesystem paths.

---

## 15. Success Criteria

The MVP is successful when:

1. The owner can fully re-theme labels, entity names, session names, rating labels, and major UI strings through `config.json` without Python code changes.
2. The owner can create people, add recurring sessions, attach media, and review history easily.
3. Audio, video, and photos display inline without leaving the current page.
4. Dashboard search and sorting make the archive easy to navigate.
5. Backup and restore work by copying `$FLEXLOG_DATA_DIR` while the app is stopped and preserving environment/configuration settings.
6. The app runs without internet access and has no obvious privacy leaks.
7. The app handles at least 300 people and 3000 sessions with acceptable local performance.

---

## Appendix A: Engineering Notes

- Require `FLEXLOG_DATA_DIR` as an absolute path environment variable.
- Use `$FLEXLOG_DATA_DIR/data/encounters.db` as the SQLite file database.
- Store per-file references as safe file keys under `$FLEXLOG_DATA_DIR/uploads/`; the only configurable filesystem path is the absolute `FLEXLOG_DATA_DIR` env var.
- Do not store absolute media paths in SQLite rows.
- Do not use an external database service or a custom JSON/YAML file database for MVP structured data.
- Keep config validation centralized.
- Avoid hardcoded template-specific nouns in backend, frontend, and JavaScript.
- For custom ratings, store by stable rating `id`, not display label.
- Gracefully handle removed or disabled rating dimensions in historical records.
- Use local static versions of JS/CSS libraries if cropper/lightbox dependencies are needed.
- Do not use remote CDNs.
- Do not transcode uploaded media in MVP.
- Browser playback depends on codec support; provide a download/open fallback for unsupported media.
- Resolve all filesystem access through a central storage service that verifies paths stay inside `$FLEXLOG_DATA_DIR`.

---

**End of PRD**
