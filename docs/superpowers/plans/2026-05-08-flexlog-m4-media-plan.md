# flexlog M4 Media + Media Library + Hash Dedup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `media_file` and `session_media` tables, the upload pipeline with SHA-256 dedup, content-addressed disk storage at `uploads/<aa>/<bb>/<sha>.<ext>`, inline `<audio>`/`<video>` playback, a PhotoSwipe-driven photo carousel + lightbox on session detail, the Media Library route with type/orphan filters and hard-delete action, and link thumbnails (using the same upload pipeline). FK constraints layer onto `Person.avatar_media_id` and `SessionLink.thumbnail_media_id` (which were free strings through M3).

**Architecture:** All disk I/O continues to go through `flexlog/paths.py` (the M1 sandbox). New service modules `flexlog/services/media.py` (upload pipeline, dedup, soft-unlink helpers) and `flexlog/services/library.py` (reference computation, orphan filter, hard delete) sit alongside the existing service layer. A new `web/media_bp.py` serves uploaded files via sandboxed `send_from_directory`; `web/library_bp.py` is the Media Library view + hard-delete POST. Session create/update routes accept `multipart/form-data` with `photos`/`audios`/`videos` file inputs, plus per-link `link_thumbnail` files and a `remove_session_media[]`/`clear_link_thumbnail[]` parallel array for soft-unlinks during edit. PhotoSwipe v5 is vendored under `static/vendor/photoswipe/` (no CDN — fetched once with curl at implementation time, committed to the repo per spec §9). Spec deviations from PRD §6.3 (content-addressed layout) and §6.10 (soft-unlink + Media Library hard-delete) take effect here for the first time.

**Tech Stack:** Python 3.11+, Flask 3.x, SQLAlchemy 2.x ORM, Flask-WTF, Jinja2, pytest. New static asset: PhotoSwipe v5.4.4 vendored.

**Source spec:** `docs/superpowers/specs/2026-05-07-flexlog-design.md` — §4 storage model, §4.4 MIME/extension matrix, §5 retention model (soft-unlink + Media Library hard-delete), §6.8 Session Detail (inline media + carousel + lightbox), §6.9 Add/Edit Session (multiple uploads), §7 data model (media_file, session_media, FK layering on avatar_media_id/thumbnail_media_id), §8 routes (`/media/<path:file_key>`, `/library`, `/library/<id>/hard_delete`, `/sessions/<id>/media/<media_file_id>/unlink`), §9 security (path traversal, MIME magic check), §11 testing, §12 M4 deliverable, §13.1/.2 PRD deviations.

**M4 deliverable:** From a fresh `FLEXLOG_DATA_DIR`, the user can:
- attach photos/audio/video to a new or existing session (multiple files per type, large files OK)
- second upload of an identical file produces only one row in `media_file` and one file on disk (verified by SHA-256)
- session detail page plays audio + video inline and shows photos in a PhotoSwipe carousel + lightbox
- add an optional thumbnail to each session link
- remove individual media from a session via the edit form (the file persists; the join row is dropped)
- visit `/library` to see every uploaded file with reference counts, filtered by type tab and an "Orphans only" toggle
- hard-delete a media file from the Media Library (cascades session_media joins; SET NULL on avatar/link-thumbnail FKs; removes the file from disk after the DB transaction commits)
- path-traversal upload attempts still rejected; XSS in original filename rendered as text
- `make test`, `make smoke`, `make run` continue to work

---

## File structure

| Path | Purpose |
|---|---|
| `flexlog/db/models.py` | **Modify**: add `MediaFile`, `SessionMedia`; layer `ForeignKey("media_file.id", ondelete="SET NULL")` onto `Person.avatar_media_id` and `SessionLink.thumbnail_media_id` |
| `flexlog/services/media.py` | **Create**: `upload_to_media_file(file_storage, type_hint) → MediaFile`, validators, `link_to_session(session, media, sort_order)`, `unlink_from_session(session_media_id)` |
| `flexlog/services/library.py` | **Create**: `MediaLibraryRow` dataclass with refs; `list_library(query=None, media_type=None, orphans_only=False)`, `get_references(media_file_id)`, `hard_delete(media_file_id)` |
| `flexlog/services/sessions.py` | **Modify**: `create_session` / `update_session` accept `media_uploads` (dict of type→list of FileStorage), `link_thumbnails` (dict of link_url→FileStorage), `remove_session_media_ids` (list), `clear_link_thumbnail_link_ids` (list) |
| `flexlog/web/forms.py` | **Modify**: extend `SessionForm` to declare file fields (or document why we don't — see Task 5 notes) |
| `flexlog/web/sessions_bp.py` | **Modify**: `create` and `update` parse `request.files` + `remove_session_media[]` + `clear_link_thumbnail[]`; pass to service |
| `flexlog/web/media_bp.py` | **Create**: `GET /media/<path:file_key>` sandboxed file serving |
| `flexlog/web/library_bp.py` | **Create**: `GET /library` (with filters), `POST /library/<media_file_id>/hard_delete`, `POST /sessions/<session_id>/media/<media_file_id>/unlink` (per spec §8 — this lives in library_bp because it's a Media Library cross-cutting action) |
| `flexlog/web/__init__.py` | **Modify**: register `media_bp`, `library_bp` |
| `flexlog/web/filters.py` | **Modify**: extend `BUILTIN_UI_DEFAULTS` with M4 keys (`media_library`, `photos_label`, `audio_label`, `videos_label`, `add_media`, `remove_media`, `orphan`, `references_count`, etc.) |
| `flexlog/app.py` | **Modify**: set `MAX_CONTENT_LENGTH` (3 GiB ceiling); sweep `uploads/.tmp/` of stale files at startup |
| `flexlog/templates/sessions/_form_body.html` | **Modify**: add file inputs for photos/audios/videos; add per-link thumbnail input + clear-thumbnail checkbox; add per-existing-media remove checkboxes |
| `flexlog/templates/sessions/detail.html` | **Modify**: render audio players, video players, photo grid with PhotoSwipe data attributes, thumbnails on link rows |
| `flexlog/templates/_partials/link_row_form.html` | **Modify**: add thumbnail file input + clear-thumbnail checkbox if existing thumbnail |
| `flexlog/templates/_partials/link_row_display.html` | **Modify**: render thumbnail next to link |
| `flexlog/templates/_partials/media_audio.html` | **Create**: single audio player |
| `flexlog/templates/_partials/media_video.html` | **Create**: single video player |
| `flexlog/templates/_partials/media_photo_thumb.html` | **Create**: photo thumbnail used by the carousel |
| `flexlog/templates/library/index.html` | **Create**: Media Library page with filters and tiles |
| `flexlog/templates/library/_partials/media_tile.html` | **Create**: one tile (thumbnail / icon, type, size, refs, actions) |
| `flexlog/templates/_base.html` | **Modify**: add nav link to "/library" |
| `flexlog/static/vendor/photoswipe/photoswipe.css` | **Create**: vendored from CDN |
| `flexlog/static/vendor/photoswipe/photoswipe.umd.min.js` | **Create**: vendored |
| `flexlog/static/vendor/photoswipe/photoswipe-lightbox.umd.min.js` | **Create**: vendored |
| `flexlog/static/js/photoswipe_init.js` | **Create**: page-scoped init that scans `.photo-grid a[data-pswp-...]` and instantiates `PhotoSwipeLightbox` |
| `flexlog/static/css/main.css` | **Append**: media-section, audio-list, video-list, photo-grid, library-grid, library-tile rules |
| `tests/unit/test_media_service.py` | **Create** |
| `tests/unit/test_library_service.py` | **Create** |
| `tests/unit/test_media_models.py` | **Create**: cascades on session_media; SET NULL on avatar/thumb FK; UNIQUE on session+media_file |
| `tests/integration/test_media_upload.py` | **Create**: full upload flow, dedup, path-traversal rejection, magic-byte rejection |
| `tests/integration/test_media_serving.py` | **Create**: GET /media/<file_key> sandboxing |
| `tests/integration/test_library_routes.py` | **Create**: list with filters, hard-delete cascades + disk unlink |
| `tests/integration/test_session_with_media.py` | **Create**: session create/edit with media, remove existing media, link thumbnails |
| `tests/integration/test_csrf.py` | **Modify**: add CSRF rejection test for `/library/<id>/hard_delete` |
| `README.md` | **Modify**: M4 features section + "What's next" |

---

## Task 1: MediaFile + SessionMedia models + FK layering

**Files:**
- Modify: `flexlog/db/models.py` — add `MediaFile`, `SessionMedia`; layer FKs onto existing `Person.avatar_media_id` and `SessionLink.thumbnail_media_id`
- Create: `tests/unit/test_media_models.py`

- [ ] **Step 1.1: Write the failing tests**

`tests/unit/test_media_models.py`:

```python
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from flexlog.db import Base, make_engine, make_session_factory
from flexlog.db.models import (
    MediaFile,
    Person,
    Session as SessionModel,
    SessionLink,
    SessionMedia,
)


@pytest.fixture
def session(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s


def _setup_session(s, link_thumbnail_id=None):
    p = Person(id="p1", alias="Alice")
    s.add(p)
    sess = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=4)
    s.add(sess)
    if link_thumbnail_id is not None:
        s.add(SessionLink(id="l1", session_id="s1", url="https://example.com", thumbnail_media_id=link_thumbnail_id))
    s.commit()
    return p, sess


def test_create_all_registers_media_tables(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {"media_file", "session_media"} <= names


def test_can_insert_media_file(session):
    mf = MediaFile(
        id="m1",
        sha256="a" * 64,
        file_key="aa/aa/" + ("a" * 64) + ".jpg",
        media_type="photo",
        original_filename="vacation.jpg",
        mime_type="image/jpeg",
        file_size_bytes=12345,
    )
    session.add(mf)
    session.commit()
    got = session.get(MediaFile, "m1")
    assert got is not None
    assert got.sha256 == "a" * 64
    assert got.media_type == "photo"
    assert got.created_at is not None


def test_media_file_sha256_unique(session):
    a = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    b = MediaFile(id="m2", sha256="a" * 64, file_key="aa/aa/y.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(a); session.commit()
    session.add(b)
    with pytest.raises(IntegrityError):
        session.commit()


def test_media_file_required_fields(session):
    bad = MediaFile(id="m1", sha256=None, file_key="x", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)  # type: ignore[arg-type]
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_session_media_links_session_and_media(session):
    _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf); session.commit()
    sm = SessionMedia(id="sm1", session_id="s1", media_file_id="m1", sort_order=0)
    session.add(sm); session.commit()
    rows = session.execute(text("SELECT session_id, media_file_id FROM session_media")).all()
    assert rows == [("s1", "m1")]


def test_session_media_unique_constraint(session):
    """A session can't have the same media file twice."""
    _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1"))
    session.commit()
    session.add(SessionMedia(id="sm2", session_id="s1", media_file_id="m1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_session_cascades_session_media(session):
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1"))
    session.commit()
    session.delete(sess); session.commit()
    # Join row gone, media_file row STILL THERE (soft-unlink semantics per spec §5)
    assert session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM media_file")).scalar() == 1


def test_deleting_media_file_cascades_session_media(session):
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1"))
    session.commit()
    session.delete(mf); session.commit()
    # Join row gone, session row STILL THERE
    assert session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM session")).scalar() == 1


def test_deleting_media_file_sets_avatar_media_id_to_null(session):
    """Hard-delete from Media Library SETs NULL on Person.avatar_media_id."""
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf); session.commit()
    p = Person(id="p1", alias="Alice", avatar_media_id="m1")
    session.add(p); session.commit()
    session.delete(mf); session.commit()
    refreshed = session.get(Person, "p1")
    assert refreshed is not None
    assert refreshed.avatar_media_id is None


def test_deleting_media_file_sets_thumbnail_media_id_to_null(session):
    """Hard-delete from Media Library SETs NULL on SessionLink.thumbnail_media_id."""
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionLink(id="l1", session_id="s1", url="https://example.com", thumbnail_media_id="m1"))
    session.commit()
    session.delete(mf); session.commit()
    refreshed_link = session.get(SessionLink, "l1")
    assert refreshed_link is not None
    assert refreshed_link.thumbnail_media_id is None


def test_session_media_relationship_navigates(session):
    p, sess = _setup_session(session)
    mf = MediaFile(id="m1", sha256="a" * 64, file_key="aa/aa/x.jpg", media_type="photo", mime_type="image/jpeg", file_size_bytes=1)
    session.add(mf)
    session.add(SessionMedia(id="sm1", session_id="s1", media_file_id="m1", sort_order=0))
    session.commit()
    refreshed = session.get(SessionModel, "s1")
    assert [m.media_file_id for m in refreshed.media_joins] == ["m1"]
    # And convenience relationship to the underlying MediaFile
    assert [j.media_file.media_type for j in refreshed.media_joins] == ["photo"]
```

- [ ] **Step 1.2: Run failing tests**

```bash
pytest tests/unit/test_media_models.py -v
```

Expected: ImportError on missing `MediaFile`/`SessionMedia`.

- [ ] **Step 1.3: Modify `flexlog/db/models.py`**

In the existing `Person` class, modify the `avatar_media_id` line:

```python
    avatar_media_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("media_file.id", ondelete="SET NULL"),
        nullable=True,
    )
```

In the existing `SessionLink` class, modify the `thumbnail_media_id` line:

```python
    thumbnail_media_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("media_file.id", ondelete="SET NULL"),
        nullable=True,
    )
```

Also append `media_joins` relationship to the `Session` class (after the existing `links` relationship):

```python
    media_joins: Mapped[List["SessionMedia"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionMedia.sort_order",
    )
```

Append at the END of the file:

```python
class MediaFile(Base):
    __tablename__ = "media_file"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sha256: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    file_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)  # 'photo' | 'audio' | 'video'
    original_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)


class SessionMedia(Base):
    __tablename__ = "session_media"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    media_file_id: Mapped[str] = mapped_column(
        String, ForeignKey("media_file.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)

    session: Mapped["Session"] = relationship(back_populates="media_joins")
    media_file: Mapped["MediaFile"] = relationship()

    __table_args__ = (
        # Spec §7: a session cannot reference the same media file twice.
        # The unique index also serves as the lookup index for ref counts.
        # SA emits this as both a UNIQUE constraint and a usable index.
        # No additional separate Index needed.
        # tuple form is required for __table_args__ when adding constraints
        # alongside any future Index() entries.
        # Note: Index on media_file_id alone is added in __table_args__ below
        # for the Media Library reference lookups.
    )


# Lookup index on session_media(media_file_id) — feeds Media Library reference
# computation. Declared here (not in __table_args__) so it works alongside the
# unique constraint without conflict; SA emits both at create_all time.
from sqlalchemy import Index, UniqueConstraint  # if not already imported

SessionMedia.__table_args__ = (
    UniqueConstraint("session_id", "media_file_id", name="uq_session_media_pair"),
    Index("ix_session_media_file", "media_file_id"),
)
```

(Important: SA accepts mutating `__table_args__` after class definition only if the table hasn't been compiled; alternatively define it inline in the class body. Use whichever style works. The plan's snippet uses post-definition assignment because the comment block above the constraints is verbose; if pytest complains, move both into the class body's `__table_args__`.)

- [ ] **Step 1.4: Run tests**

```bash
pytest -v
```

Expected: 11 new model tests pass; all 267 prior tests still pass; coverage gate green.

- [ ] **Step 1.5: Commit**

```bash
git add flexlog/db/models.py tests/unit/test_media_models.py
git commit -m "M4: add MediaFile + SessionMedia models with cascade/SET NULL FKs

Person.avatar_media_id and SessionLink.thumbnail_media_id gain
ON DELETE SET NULL FK to media_file. SessionMedia (the join) gains
ON DELETE CASCADE on both sides. UNIQUE(session_id, media_file_id)
prevents duplicate links of the same file to one session. Index on
media_file_id feeds Media Library reference lookups."
```

---

## Task 2: `services/media.py` — upload pipeline + dedup

**Files:**
- Create: `flexlog/services/media.py`
- Create: `tests/unit/test_media_service.py`

The pipeline:
1. Stream-write the incoming `FileStorage` to a tmp file in `paths.tmp_uploads_dir()` while computing SHA-256 in chunks (using `flexlog.hashing.sha256_hex_stream`).
2. Validate: size ≤ `config.limits.max_upload_mb_per_file`; extension allowed; MIME magic-byte check for images.
3. Compute `file_key = paths.file_key_for(sha, mime)`.
4. Dedup: if `media_file.sha256 == sha` exists, delete tmp, return existing.
5. Else: ensure parent dirs exist; `os.replace(tmp, target)`; insert `MediaFile` row.

- [ ] **Step 2.1: Write failing tests**

`tests/unit/test_media_service.py`:

```python
import hashlib
import io

import pytest
from werkzeug.datastructures import FileStorage

from flexlog import paths
from flexlog.db.models import MediaFile
from flexlog.services.media import (
    MediaUploadError,
    UnsupportedMediaTypeError,
    _detect_mime_from_bytes,
    upload_to_media_file,
)


# Tiny valid signatures — the magic-byte detection only needs the first ~12 bytes.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100
WAV_BYTES = b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 100
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100  # ID3v2 header
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 100
WEBM_BYTES = b"\x1a\x45\xdf\xa3" + b"\x00" * 100  # EBML signature


def _file_storage(name: str, data: bytes, mimetype: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type=mimetype)


def test_upload_creates_media_file_row(app, db_session, tmp_data_dir):
    """Happy path: upload a JPEG, get a MediaFile row + a file on disk."""
    with app.app_context():
        fs = _file_storage("vacation.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        assert isinstance(mf, MediaFile)
        assert mf.media_type == "photo"
        assert mf.mime_type == "image/jpeg"
        assert mf.file_size_bytes == len(JPEG_BYTES)
        assert mf.original_filename == "vacation.jpg"
        # File exists at the resolved key
        target = paths.resolve_file_key(mf.file_key)
        assert target.exists()
        assert target.read_bytes() == JPEG_BYTES


def test_upload_dedup_by_sha256(app, db_session):
    """Uploading identical bytes twice produces ONE row and ONE file on disk."""
    with app.app_context():
        fs1 = _file_storage("a.jpg", JPEG_BYTES, "image/jpeg")
        mf1 = upload_to_media_file(db_session, fs1)
        db_session.commit()
        fs2 = _file_storage("b.jpg", JPEG_BYTES, "image/jpeg")  # different name, same bytes
        mf2 = upload_to_media_file(db_session, fs2)
        db_session.commit()
        assert mf1.id == mf2.id  # same row reused
        assert mf1.original_filename == "a.jpg"  # first-seen wins
        # Single file on disk
        target = paths.resolve_file_key(mf1.file_key)
        assert target.exists()
        # uploads/.tmp/ is empty
        tmp_dir = paths.tmp_uploads_dir()
        assert list(tmp_dir.iterdir()) == [] or all(not f.is_file() for f in tmp_dir.iterdir())


def test_upload_classifies_mime(app, db_session):
    """media_type is derived from MIME for each supported family."""
    with app.app_context():
        for name, data, mimetype, expected_type in [
            ("a.jpg", JPEG_BYTES, "image/jpeg", "photo"),
            ("a.png", PNG_BYTES, "image/png", "photo"),
            ("a.webp", WEBP_BYTES, "image/webp", "photo"),
            ("a.mp3", MP3_BYTES, "audio/mpeg", "audio"),
            ("a.wav", WAV_BYTES, "audio/wav", "audio"),
            ("a.mp4", MP4_BYTES, "video/mp4", "video"),
            ("a.webm", WEBM_BYTES, "video/webm", "video"),
        ]:
            fs = _file_storage(name, data, mimetype)
            mf = upload_to_media_file(db_session, fs)
            db_session.commit()
            assert mf.media_type == expected_type, f"{mimetype} → expected {expected_type}, got {mf.media_type}"


def test_upload_rejects_unsupported_mime(app, db_session):
    """A .pdf or .exe upload is rejected at the MIME-allowlist gate."""
    with app.app_context():
        fs = _file_storage("evil.exe", b"MZ\x90\x00" * 100, "application/octet-stream")
        with pytest.raises(UnsupportedMediaTypeError):
            upload_to_media_file(db_session, fs)


def test_upload_rejects_mime_extension_mismatch(app, db_session):
    """An attacker tries to pass .exe contents with a JPEG MIME type."""
    with app.app_context():
        fs = _file_storage("evil.jpg", b"MZ\x90\x00" * 100, "image/jpeg")
        with pytest.raises(MediaUploadError, match="magic"):
            upload_to_media_file(db_session, fs)


def test_upload_rejects_size_over_limit(app, db_session):
    """File exceeding config.limits.max_upload_mb_per_file is rejected."""
    with app.app_context():
        big = JPEG_BYTES + b"\x00" * (1024 * 1024)  # ~1 MB
        # Force the limit down to 0 MB to trip the guard regardless of file size
        cfg = app.config["FLEXLOG"]
        # Replace the frozen Limits dataclass by rebuilding it inline
        from dataclasses import replace
        new_limits = replace(cfg.limits, max_upload_mb_per_file=0)
        from dataclasses import replace as cfg_replace
        app.config["FLEXLOG"] = cfg_replace(cfg, limits=new_limits)
        fs = _file_storage("big.jpg", big, "image/jpeg")
        with pytest.raises(MediaUploadError, match="size"):
            upload_to_media_file(db_session, fs)


def test_upload_temp_file_cleaned_up_on_error(app, db_session):
    """When upload fails mid-pipeline, the tmp file is removed."""
    with app.app_context():
        fs = _file_storage("evil.exe", b"MZ" * 1000, "application/octet-stream")
        with pytest.raises(UnsupportedMediaTypeError):
            upload_to_media_file(db_session, fs)
        # No file should remain in .tmp
        from flexlog import paths as p
        leftover = list((p.tmp_uploads_dir()).iterdir())
        # filter to regular files (not subdirs)
        leftover = [x for x in leftover if x.is_file()]
        assert leftover == []


def test_upload_writes_correct_disk_path(app, db_session):
    """Verifies the content-addressed sharded layout: <aa>/<bb>/<sha>.<ext>."""
    with app.app_context():
        fs = _file_storage("vacation.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        sha = hashlib.sha256(JPEG_BYTES).hexdigest()
        assert mf.sha256 == sha
        assert mf.file_key == f"{sha[0:2]}/{sha[2:4]}/{sha}.jpg"


def test_detect_mime_from_bytes_signatures():
    """Pure-function magic-byte → MIME detector."""
    assert _detect_mime_from_bytes(JPEG_BYTES) == "image/jpeg"
    assert _detect_mime_from_bytes(PNG_BYTES) == "image/png"
    assert _detect_mime_from_bytes(WEBP_BYTES) == "image/webp"
    # Non-image: returns None (audio/video are accepted by extension+content-type only)
    assert _detect_mime_from_bytes(b"random text") is None


def test_upload_rejects_empty_file(app, db_session):
    with app.app_context():
        fs = _file_storage("empty.jpg", b"", "image/jpeg")
        with pytest.raises(MediaUploadError, match="empty"):
            upload_to_media_file(db_session, fs)


def test_upload_preserves_original_filename(app, db_session):
    """original_filename is recorded for display."""
    with app.app_context():
        fs = _file_storage("My Vacation 2026.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        assert mf.original_filename == "My Vacation 2026.jpg"


def test_upload_handles_filename_with_path_traversal(app, db_session):
    """An attacker-controlled filename like '../../etc/passwd.jpg' must not
    affect the on-disk path; the path is derived from the SHA-256, not the
    original filename.
    """
    with app.app_context():
        fs = _file_storage("../../etc/passwd.jpg", JPEG_BYTES, "image/jpeg")
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
        # The file lives under uploads/<aa>/<bb>/<sha>.jpg, not under any
        # parent of uploads/.
        target = paths.resolve_file_key(mf.file_key)
        assert paths.uploads_dir() in target.parents or target.parent.parent.parent == paths.uploads_dir()
        # original_filename is recorded as-is — escaping happens at render time.
        assert mf.original_filename == "../../etc/passwd.jpg"
```

- [ ] **Step 2.2: Run failing tests**

Expected: ImportError on missing module.

- [ ] **Step 2.3: Implement `flexlog/services/media.py`**

```python
"""Upload pipeline + content-addressed storage.

The pipeline streams the incoming FileStorage to a tmp file inside
$FLEXLOG_DATA_DIR/uploads/.tmp/, computes SHA-256 in chunks, validates
size + MIME, and then either deduplicates against an existing media_file
row (deleting the tmp) or atomically renames the tmp into the canonical
content-addressed location and inserts a fresh media_file row.

Magic-byte detection is implemented for images only (JPEG, PNG, WebP) per
spec §4.3 — audio and video are validated by content-type/extension match
since their formats are too varied for a small signature check.
"""

from __future__ import annotations

import os
import secrets
import uuid
from pathlib import Path

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from flexlog import paths
from flexlog.db.models import MediaFile, SessionMedia
from flexlog.hashing import sha256_hex_stream

CHUNK = 1024 * 1024  # 1 MiB


class MediaUploadError(RuntimeError):
    """Raised when an upload fails validation."""


class UnsupportedMediaTypeError(MediaUploadError):
    """Raised when MIME type is outside the allowlist."""


# MIME → media_type classification (matches paths._MIME_TO_EXT keys)
_MIME_TO_TYPE: dict[str, str] = {
    "image/jpeg": "photo",
    "image/png": "photo",
    "image/webp": "photo",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "audio/mp4": "audio",
    "audio/x-m4a": "audio",
    "video/mp4": "video",
    "video/webm": "video",
    "video/quicktime": "video",
}


def _detect_mime_from_bytes(head: bytes) -> str | None:
    """Match the first ~12 bytes against image signatures. Returns None if
    not a recognized image (audio/video aren't checked here).
    """
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def upload_to_media_file(db: Session, fs: FileStorage) -> MediaFile:
    """Run an uploaded FileStorage through the pipeline → MediaFile row.

    Caller is responsible for committing. The MediaFile row is added to the
    session via add() but not committed; downstream code (e.g. linking the
    file to a session) typically commits after composing the full graph.

    On dedup, returns the existing row without modifying it.
    """
    declared_mime = fs.mimetype or ""
    if declared_mime not in _MIME_TO_TYPE:
        raise UnsupportedMediaTypeError(
            f"unsupported MIME type {declared_mime!r}; "
            f"allowed: {sorted(_MIME_TO_TYPE)}"
        )

    cfg = current_app.config["FLEXLOG"]
    max_bytes = cfg.limits.max_upload_mb_per_file * 1024 * 1024

    paths.ensure_layout()
    tmp_dir = paths.tmp_uploads_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_name = secrets.token_hex(16) + ".part"
    tmp_path = tmp_dir / tmp_name

    sha = ""
    size = 0
    head_bytes = b""

    try:
        with tmp_path.open("wb") as out:
            import hashlib
            h = hashlib.sha256()
            while True:
                chunk = fs.stream.read(CHUNK)
                if not chunk:
                    break
                if not head_bytes:
                    head_bytes = chunk[:64]  # capture the first chunk's head for magic-byte check
                size += len(chunk)
                if max_bytes > 0 and size > max_bytes:
                    raise MediaUploadError(
                        f"upload exceeds size cap of {cfg.limits.max_upload_mb_per_file} MiB"
                    )
                h.update(chunk)
                out.write(chunk)
            sha = h.hexdigest()

        if size == 0:
            raise MediaUploadError("upload is empty")

        # Image MIMEs: cross-check magic bytes
        if declared_mime in ("image/jpeg", "image/png", "image/webp"):
            detected = _detect_mime_from_bytes(head_bytes)
            if detected != declared_mime:
                raise MediaUploadError(
                    f"declared MIME {declared_mime!r} does not match magic bytes ({detected!r})"
                )

        media_type = _MIME_TO_TYPE[declared_mime]
        file_key = paths.file_key_for(sha, declared_mime)

        # Dedup: existing row?
        existing = db.execute(
            select(MediaFile).where(MediaFile.sha256 == sha)
        ).scalar_one_or_none()
        if existing is not None:
            # Drop the tmp; reuse the existing row.
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            return existing

        # New file: ensure target directory, atomic rename.
        target = paths.resolve_file_key(file_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, target)

        new_row = MediaFile(
            id=str(uuid.uuid4()),
            sha256=sha,
            file_key=file_key,
            media_type=media_type,
            original_filename=fs.filename,
            mime_type=declared_mime,
            file_size_bytes=size,
        )
        db.add(new_row)
        db.flush()
        return new_row
    except Exception:
        # Best-effort cleanup
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def link_to_session(
    db: Session, session_id: str, media_file_id: str, sort_order: int = 0
) -> SessionMedia:
    """Create the session_media join. Caller commits."""
    sm = SessionMedia(
        id=str(uuid.uuid4()),
        session_id=session_id,
        media_file_id=media_file_id,
        sort_order=sort_order,
    )
    db.add(sm)
    db.flush()
    return sm


def unlink_from_session(db: Session, session_media_id: str) -> None:
    """Soft-unlink: remove the session_media join. Media file persists."""
    sm = db.get(SessionMedia, session_media_id)
    if sm is not None:
        db.delete(sm)
```

- [ ] **Step 2.4: Run tests, verify pass**

Expected: all 12 new tests pass; existing 267 still pass.

- [ ] **Step 2.5: Commit**

```bash
git add flexlog/services/media.py tests/unit/test_media_service.py
git commit -m "M4: add media upload pipeline with SHA-256 dedup

Streams uploads to uploads/.tmp/, computes SHA-256, validates size +
MIME (magic-byte check for images), and either reuses an existing
media_file row by sha256 or atomically renames the tmp into the
canonical content-addressed location at <aa>/<bb>/<sha>.<ext>.
link_to_session / unlink_from_session helpers handle the join."
```

---

## Task 3: `services/library.py` — references + orphans + hard delete

**Files:**
- Create: `flexlog/services/library.py`
- Create: `tests/unit/test_library_service.py`

- [ ] **Step 3.1: Write failing tests**

`tests/unit/test_library_service.py`:

```python
import io

import pytest
from werkzeug.datastructures import FileStorage

from flexlog import paths
from flexlog.db.models import MediaFile, Person, SessionLink
from flexlog.services.library import (
    MediaLibraryRow,
    get_references,
    hard_delete,
    list_library,
)
from flexlog.services.media import upload_to_media_file
from flexlog.services.people import create_person
from flexlog.services.sessions import create_session

JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100
MP3_BYTES = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100


def _upload(app, db_session, name, data, mimetype):
    fs = FileStorage(stream=io.BytesIO(data), filename=name, content_type=mimetype)
    with app.app_context():
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
    return mf


def test_list_library_empty(db_session):
    assert list_library(db_session) == []


def test_list_library_returns_all_media(app, db_session):
    a = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    b = _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    rows = list_library(db_session)
    assert len(rows) == 2
    ids = {r.media_file.id for r in rows}
    assert ids == {a.id, b.id}


def test_list_library_filter_by_type(app, db_session):
    _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    photos = list_library(db_session, media_type="photo")
    audios = list_library(db_session, media_type="audio")
    videos = list_library(db_session, media_type="video")
    assert {r.media_file.media_type for r in photos} == {"photo"}
    assert {r.media_file.media_type for r in audios} == {"audio"}
    assert videos == []


def test_orphan_filter_includes_only_unreferenced(app, db_session):
    """A file referenced by a session is not an orphan; one with no refs is."""
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    orphan_audio = _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    # link the photo to a session
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=4, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    from flexlog.services.media import link_to_session
    link_to_session(db_session, s.id, photo.id, sort_order=0)
    db_session.commit()
    # orphan filter
    rows = list_library(db_session, orphans_only=True)
    ids = {r.media_file.id for r in rows}
    assert ids == {orphan_audio.id}


def test_get_references_counts_session_media(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s1 = create_session(db_session, person_id=p.id, session_date="2026-04-01", overall_score=3, custom_ratings={}, notes=None, links=[])
    s2 = create_session(db_session, person_id=p.id, session_date="2026-05-01", overall_score=4, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    from flexlog.services.media import link_to_session
    link_to_session(db_session, s1.id, photo.id)
    link_to_session(db_session, s2.id, photo.id)
    db_session.commit()
    refs = get_references(db_session, photo.id)
    assert refs.session_media_count == 2
    assert refs.avatar_count == 0
    assert refs.link_thumbnail_count == 0
    assert refs.total == 2


def test_get_references_counts_avatar(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = Person(id="p1", alias="Alice", avatar_media_id=photo.id)
    db_session.add(p); db_session.commit()
    refs = get_references(db_session, photo.id)
    assert refs.avatar_count == 1
    assert refs.session_media_count == 0


def test_get_references_counts_link_thumbnail(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(
        db_session, person_id=p.id, session_date="2026-04-01", overall_score=3,
        custom_ratings={}, notes=None,
        links=[{"url": "https://example.com", "label": "x"}],
    )
    db_session.commit()
    # set thumbnail manually
    s.links[0].thumbnail_media_id = photo.id
    db_session.commit()
    refs = get_references(db_session, photo.id)
    assert refs.link_thumbnail_count == 1


def test_hard_delete_removes_row_and_disk_file(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    target = paths.resolve_file_key(photo.file_key)
    assert target.exists()
    with app.app_context():
        hard_delete(db_session, photo.id)
        db_session.commit()
    # DB row gone
    assert db_session.get(MediaFile, photo.id) is None
    # Disk file gone
    assert not target.exists()


def test_hard_delete_cascades_session_media_and_nulls_avatar(app, db_session):
    """Hard-delete from Library: session_media joins go via cascade; avatar
    FK SET NULL.
    """
    from sqlalchemy import text

    from flexlog.services.media import link_to_session

    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    p.avatar_media_id = photo.id
    s = create_session(db_session, person_id=p.id, session_date="2026-04-01", overall_score=3, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    link_to_session(db_session, s.id, photo.id, sort_order=0)
    db_session.commit()

    assert db_session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 1
    with app.app_context():
        hard_delete(db_session, photo.id)
        db_session.commit()
    db_session.expire_all()
    assert db_session.execute(text("SELECT COUNT(*) FROM session_media")).scalar() == 0
    refreshed_p = db_session.get(Person, p.id)
    assert refreshed_p.avatar_media_id is None


def test_hard_delete_missing_id_raises(app, db_session):
    from flexlog.services.library import MediaNotFoundError
    with app.app_context():
        with pytest.raises(MediaNotFoundError):
            hard_delete(db_session, "nope")


def test_list_library_orders_newest_first(app, db_session):
    a = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    b = _upload(app, db_session, "b.mp3", MP3_BYTES, "audio/mpeg")
    rows = list_library(db_session)
    # b uploaded after a, expect b first
    assert rows[0].media_file.id == b.id
    assert rows[1].media_file.id == a.id


def test_media_library_row_total_refs(app, db_session):
    photo = _upload(app, db_session, "a.jpg", JPEG_BYTES, "image/jpeg")
    rows = list_library(db_session)
    assert len(rows) == 1
    assert isinstance(rows[0], MediaLibraryRow)
    assert rows[0].total_refs == 0
    assert rows[0].is_orphan
```

- [ ] **Step 3.2: Run failing tests**

Expected: ImportError on missing module.

- [ ] **Step 3.3: Implement `flexlog/services/library.py`**

```python
"""Media Library queries: list with reference counts, orphan filter, hard delete.

Hard-delete is the ONLY route that removes a file from disk. It must:
  1. Inside one DB transaction: delete session_media joins (FK CASCADE);
     null out person.avatar_media_id and session_link.thumbnail_media_id
     (FK SET NULL); delete the media_file row.
  2. After commit: paths.resolve_file_key(...).unlink(missing_ok=True).

Order matters: DB commit FIRST, disk unlink SECOND. A failure between
the two leaves an orphaned file on disk (recoverable manually) rather
than a dangling DB row pointing at a deleted file.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from flexlog import paths
from flexlog.db.models import MediaFile, Person, SessionLink, SessionMedia


class MediaNotFoundError(LookupError):
    """Raised by hard_delete when the target media_file id does not exist."""


@dataclass(frozen=True)
class References:
    session_media_count: int
    avatar_count: int
    link_thumbnail_count: int

    @property
    def total(self) -> int:
        return self.session_media_count + self.avatar_count + self.link_thumbnail_count


@dataclass(frozen=True)
class MediaLibraryRow:
    media_file: MediaFile
    total_refs: int

    @property
    def is_orphan(self) -> bool:
        return self.total_refs == 0


def get_references(db: Session, media_file_id: str) -> References:
    """Count references across session_media, person.avatar_media_id,
    session_link.thumbnail_media_id.
    """
    sm = db.execute(
        select(func.count()).select_from(SessionMedia).where(SessionMedia.media_file_id == media_file_id)
    ).scalar_one()
    avatar = db.execute(
        select(func.count()).select_from(Person).where(Person.avatar_media_id == media_file_id)
    ).scalar_one()
    thumb = db.execute(
        select(func.count()).select_from(SessionLink).where(SessionLink.thumbnail_media_id == media_file_id)
    ).scalar_one()
    return References(
        session_media_count=int(sm),
        avatar_count=int(avatar),
        link_thumbnail_count=int(thumb),
    )


def list_library(
    db: Session,
    media_type: str | None = None,
    orphans_only: bool = False,
) -> list[MediaLibraryRow]:
    """List MediaLibraryRows (newest first), optionally filtered."""
    stmt = select(MediaFile).order_by(MediaFile.created_at.desc())
    if media_type is not None:
        stmt = stmt.where(MediaFile.media_type == media_type)
    files = list(db.execute(stmt).scalars())

    out: list[MediaLibraryRow] = []
    for mf in files:
        refs = get_references(db, mf.id)
        if orphans_only and refs.total > 0:
            continue
        out.append(MediaLibraryRow(media_file=mf, total_refs=refs.total))
    return out


def hard_delete(db: Session, media_file_id: str) -> None:
    """Hard-delete a media file: cascade joins, null out FKs, drop row, unlink disk file.

    Caller is responsible for `db.commit()` after the call. The disk unlink
    happens AFTER the commit in the same call (so a partial failure never
    leaves a dangling DB row).
    """
    mf = db.get(MediaFile, media_file_id)
    if mf is None:
        raise MediaNotFoundError(media_file_id)
    file_key = mf.file_key
    # The FK constraints handle cascade (session_media) and SET NULL (avatar,
    # thumbnail). Just delete the row.
    db.delete(mf)
    db.flush()
    # The caller should commit AFTER this returns. We perform the disk unlink
    # only after the caller commits. To honor the spec's commit-then-unlink
    # ordering we expose a deferred-unlink mechanism: stash the file_key on
    # the session's info dict so the caller (e.g. the route handler) can
    # unlink after commit. But for service ergonomics we offer the simpler
    # contract: caller commits, then calls a partner function. To keep the
    # API one-call-per-action, we instead do: delete + flush, then on commit
    # we unlink. Easiest way: use SQLAlchemy event 'after_commit'.
    #
    # See docs/superpowers/specs/2026-05-07-flexlog-design.md §5.2.
    from sqlalchemy import event

    def _unlink_after_commit(_session):
        try:
            paths.resolve_file_key(file_key).unlink(missing_ok=True)
        except Exception:
            # Disk failure leaves an orphaned file (recoverable manually).
            pass
        # Detach the listener so it only fires once for this delete.
        event.remove(db, "after_commit", _unlink_after_commit)

    event.listen(db, "after_commit", _unlink_after_commit)
```

- [ ] **Step 3.4: Run tests, verify pass**

Expected: 11 new tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add flexlog/services/library.py tests/unit/test_library_service.py
git commit -m "M4: add Media Library service — refs, orphans, hard delete

list_library() returns MediaLibraryRow with total_refs and is_orphan;
filter by media_type and orphans_only. get_references() counts across
session_media, avatar_media_id, link.thumbnail_media_id. hard_delete()
deletes the row + cascades + SETs NULL + unlinks the disk file via an
after-commit event listener so the disk unlink only happens after the
DB transaction succeeds (spec §5.2)."
```

---

## Task 4: `web/media_bp.py` — sandboxed file serving

**Files:**
- Create: `flexlog/web/media_bp.py`
- Modify: `flexlog/web/__init__.py`
- Create: `tests/integration/test_media_serving.py`

- [ ] **Step 4.1: Write tests**

`tests/integration/test_media_serving.py`:

```python
import io

from werkzeug.datastructures import FileStorage

from flexlog.services.media import upload_to_media_file


JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100


def _upload(app, db_session, data=JPEG_BYTES, mime="image/jpeg", name="x.jpg"):
    fs = FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)
    with app.app_context():
        mf = upload_to_media_file(db_session, fs)
        db_session.commit()
    return mf


def test_serve_uploaded_file(client, app, db_session):
    mf = _upload(app, db_session)
    resp = client.get(f"/media/{mf.file_key}")
    assert resp.status_code == 200
    assert resp.data == JPEG_BYTES
    assert resp.mimetype == "image/jpeg"


def test_serve_traversal_attempt_404(client):
    resp = client.get("/media/../../etc/passwd")
    # Werkzeug normalizes '..' but our route still rejects via resolve_file_key
    assert resp.status_code in (400, 403, 404)


def test_serve_unknown_file_404(client):
    # Valid-looking but non-existent file_key
    bogus_key = "ab/cd/" + ("0" * 64) + ".jpg"
    resp = client.get(f"/media/{bogus_key}")
    assert resp.status_code == 404


def test_serve_absolute_path_in_key_404(client):
    resp = client.get("/media/%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)
```

- [ ] **Step 4.2: Implement `flexlog/web/media_bp.py`**

```python
"""Sandboxed media file serving."""

from __future__ import annotations

from flask import Blueprint, abort, send_from_directory

from flexlog import paths
from flexlog.paths import FileKeyError

media_bp = Blueprint("media", __name__)


@media_bp.get("/media/<path:file_key>")
def serve(file_key: str):
    try:
        target = paths.resolve_file_key(file_key)
    except FileKeyError:
        abort(404)
    if not target.is_file():
        abort(404)
    # send_from_directory takes the directory + filename. We use the parent
    # of the resolved path to keep the sandbox tight.
    return send_from_directory(target.parent, target.name)
```

- [ ] **Step 4.3: Update `flexlog/web/__init__.py`**

```python
from flexlog.web.dashboard_bp import dashboard_bp
from flexlog.web.media_bp import media_bp
from flexlog.web.people_bp import people_bp
from flexlog.web.sessions_bp import sessions_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(media_bp)
```

- [ ] **Step 4.4: Run tests, verify pass + commit**

```bash
git add flexlog/web/media_bp.py flexlog/web/__init__.py tests/integration/test_media_serving.py
git commit -m "M4: serve media via /media/<file_key> sandboxed by paths.resolve_file_key

resolve_file_key normalizes through Path.resolve() and asserts containment
under uploads_dir(). Traversal, NUL bytes, absolute paths, and symlink
escape all yield FileKeyError, which the route translates to 404."
```

---

## Task 5: Session form upload handling

**Files:**
- Modify: `flexlog/services/sessions.py`
- Modify: `flexlog/web/sessions_bp.py`
- Modify: `flexlog/web/forms.py` (optional — add `MultipleFileField` for cleaner declaration; if it conflicts with our `request.files` parsing, drop the FieldList approach and stay with direct request.files reads)
- Create: `tests/integration/test_session_with_media.py`

- [ ] **Step 5.1: Extend `services/sessions.py:create_session` and `update_session` signatures**

Replace the signatures to accept media:

```python
def create_session(
    db: Session,
    person_id: str,
    session_date: str,
    overall_score: int,
    custom_ratings: dict[str, int],
    notes: str | None,
    links: list[dict],
    media_uploads: list[tuple] | None = None,        # list of (FileStorage,) — type derived from MIME
    link_thumbnails: list[FileStorage | None] | None = None,  # parallel to links
) -> SessionRow:
```

Add `from werkzeug.datastructures import FileStorage` and `from flexlog.services.media import upload_to_media_file, link_to_session` at the top.

Inside `create_session`, after the `_replace_links(...)` call:

```python
    # Handle media attachments
    if media_uploads:
        next_sort = 0
        for fs in media_uploads:
            if fs is None or fs.filename == "":
                continue
            mf = upload_to_media_file(db, fs)
            link_to_session(db, session_row.id, mf.id, sort_order=next_sort)
            next_sort += 1

    # Handle link thumbnails (parallel to session_row.links via index)
    if link_thumbnails:
        for i, thumb_fs in enumerate(link_thumbnails):
            if thumb_fs is None or thumb_fs.filename == "":
                continue
            if i >= len(session_row.links):
                continue
            mf = upload_to_media_file(db, thumb_fs)
            session_row.links[i].thumbnail_media_id = mf.id
```

For `update_session`, accept additional kwargs:

```python
def update_session(
    db: Session,
    session_id: str,
    session_date: str,
    overall_score: int,
    custom_ratings: dict[str, int],
    notes: str | None,
    links: list[dict],
    media_uploads: list | None = None,
    link_thumbnails: list | None = None,
    remove_session_media_ids: list[str] | None = None,
    clear_link_thumbnail_link_ids: list[str] | None = None,
) -> SessionRow:
```

In the body, after `_replace_links(...)`:

```python
    # Soft-unlink existing media joins
    if remove_session_media_ids:
        from flexlog.services.media import unlink_from_session
        for sm_id in remove_session_media_ids:
            unlink_from_session(db, sm_id)

    # Clear link thumbnails (by link.id — only valid for links that survived)
    if clear_link_thumbnail_link_ids:
        for link in session_row.links:
            if link.id in set(clear_link_thumbnail_link_ids):
                link.thumbnail_media_id = None

    # Handle new media uploads
    if media_uploads:
        # Compute next sort_order beyond any existing
        existing_max = max((sm.sort_order for sm in session_row.media_joins), default=-1)
        next_sort = existing_max + 1
        for fs in media_uploads:
            if fs is None or fs.filename == "":
                continue
            mf = upload_to_media_file(db, fs)
            link_to_session(db, session_id, mf.id, sort_order=next_sort)
            next_sort += 1

    # Handle new link thumbnails (parallel to current session_row.links)
    if link_thumbnails:
        for i, thumb_fs in enumerate(link_thumbnails):
            if thumb_fs is None or thumb_fs.filename == "":
                continue
            if i >= len(session_row.links):
                continue
            mf = upload_to_media_file(db, thumb_fs)
            session_row.links[i].thumbnail_media_id = mf.id
```

Existing service tests should still pass (defaults are None/empty). Run pytest.

- [ ] **Step 5.2: Update `web/sessions_bp.py:create` and `update` to parse multipart**

Add a helper to read multipart files:

```python
def _gather_uploads() -> list:
    """Gather all uploaded files from photos[], audios[], videos[] into a single list."""
    out = []
    for name in ("photos", "audios", "videos"):
        for fs in request.files.getlist(name):
            if fs and fs.filename:
                out.append(fs)
    return out


def _gather_link_thumbnails() -> list:
    """Read link_thumbnail[] file inputs (parallel to link_url[] / link_label[])."""
    return list(request.files.getlist("link_thumbnail"))
```

Update the `create` route to pass these to `create_session` and the `update` route to also pass:

```python
remove_session_media_ids=request.form.getlist("remove_session_media"),
clear_link_thumbnail_link_ids=request.form.getlist("clear_link_thumbnail"),
```

- [ ] **Step 5.3: Write `tests/integration/test_session_with_media.py`**

```python
import io

from werkzeug.datastructures import FileStorage


JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100


def _person(db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    return p


def test_create_session_with_one_photo(client, db_session):
    p = _person(db_session)
    data = {
        "session_date": "2026-04-15",
        "overall_score": "4",
        "photos": (io.BytesIO(JPEG_BYTES), "vacation.jpg", "image/jpeg"),
    }
    resp = client.post(f"/people/{p.id}/sessions", data=data, content_type="multipart/form-data", follow_redirects=False)
    assert resp.status_code == 302
    from flexlog.db.models import MediaFile, SessionMedia
    media_files = db_session.query(MediaFile).all()
    assert len(media_files) == 1
    assert media_files[0].media_type == "photo"
    joins = db_session.query(SessionMedia).all()
    assert len(joins) == 1


def test_dedup_when_same_bytes_uploaded_twice(client, db_session):
    p = _person(db_session)
    # First session with the photo
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "first.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    # Second session, same bytes, different filename
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-16", "overall_score": "5", "photos": (io.BytesIO(JPEG_BYTES), "second.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import MediaFile
    rows = db_session.query(MediaFile).all()
    assert len(rows) == 1, f"expected dedup; got {len(rows)} rows"
    assert rows[0].original_filename == "first.jpg"  # first-seen wins


def test_remove_existing_media_unlinks_join_only(client, db_session):
    """Editing a session with remove_session_media[<sm_id>] drops the join,
    leaves the file on disk + media_file row."""
    p = _person(db_session)
    # Create session with a photo
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import MediaFile, Session as SessionRow, SessionMedia
    sess = db_session.query(SessionRow).first()
    sm = db_session.query(SessionMedia).first()
    # Edit: remove the join
    resp = client.post(
        f"/sessions/{sess.id}",
        data={"session_date": "2026-04-15", "overall_score": "4", "remove_session_media": [sm.id]},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db_session.expire_all()
    assert db_session.query(SessionMedia).count() == 0
    assert db_session.query(MediaFile).count() == 1  # file persists


def test_link_thumbnail_attached(client, db_session):
    p = _person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15",
            "overall_score": "4",
            "link_url": ["https://example.com"],
            "link_label": ["Ref"],
            "link_thumbnail": [(io.BytesIO(JPEG_BYTES), "thumb.jpg", "image/jpeg")],
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    from flexlog.db.models import SessionLink
    link = db_session.query(SessionLink).first()
    assert link.thumbnail_media_id is not None


def test_traversal_filename_does_not_escape_uploads(client, db_session):
    """An uploader's malicious filename with .. doesn't escape uploads/."""
    from flexlog import paths
    p = _person(db_session)
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "../../escape.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    # The on-disk path is content-addressed, not filename-derived, so this
    # should always be inside uploads_dir.
    from flexlog.db.models import MediaFile
    mf = db_session.query(MediaFile).first()
    target = paths.resolve_file_key(mf.file_key)
    assert paths.uploads_dir().resolve() in target.resolve().parents
```

- [ ] **Step 5.4: Run tests + commit**

```bash
git add flexlog/services/sessions.py flexlog/web/sessions_bp.py tests/integration/test_session_with_media.py
git commit -m "M4: wire session create/update routes to upload pipeline

photos[], audios[], videos[] file fields → upload_to_media_file →
SessionMedia join. link_thumbnail[] (parallel to link_url[]) → upload
+ set link.thumbnail_media_id. remove_session_media[] drops joins;
clear_link_thumbnail[] nulls link thumbnails. files persist on disk
(soft-unlink semantics — Media Library hard-deletes them per spec §5)."
```

---

## Task 6: Session form template — file inputs + remove checkboxes

**Files:**
- Modify: `flexlog/templates/sessions/_form_body.html` — add file inputs for photos/audios/videos; per-existing-media-row remove checkbox; per-link thumbnail file input + clear-thumbnail checkbox
- Modify: `flexlog/templates/_partials/link_row_form.html` — add thumbnail file input + clear checkbox if existing
- Modify: `flexlog/web/sessions_bp.py:edit/new` — pass `existing_media` (list of session_media joins) and `existing_link_thumbnails` to template

Plan:

In `flexlog/web/sessions_bp.py`, update the `edit` view to pass existing media to the template:

```python
@sessions_bp.get("/sessions/<session_id>/edit")
def edit(session_id: str):
    s = _session_or_404(session_id)
    form = SessionForm(data={...})
    enabled_ids = [d.id for d in _enabled_rating_dimensions()]
    current_pairs, _archived = split_custom_ratings(s.custom_ratings_json, enabled_ids)
    existing_ratings = dict(current_pairs)
    existing_links = [{"id": li.id, "url": li.url, "label": li.label or "", "thumbnail_media_id": li.thumbnail_media_id} for li in s.links]
    existing_media = list(s.media_joins)  # SessionMedia rows; template reads .media_file.{file_key, original_filename, media_type}
    return render_template(
        "sessions/edit.html",
        form=form, person=s.person, session=s,
        rating_dimensions=_enabled_rating_dimensions(),
        existing_ratings=existing_ratings,
        existing_links=existing_links,
        existing_media=existing_media,
    )
```

Update `new` similarly to pass `existing_media=[]`.

In `flexlog/templates/sessions/_form_body.html`, add **before** the `<fieldset class="links-row">`:

```jinja
{# Existing media (only on edit; new is empty) #}
{% if existing_media %}
<fieldset class="form-row existing-media">
  <legend>Attached media</legend>
  <ul class="existing-media-list">
    {% for sm in existing_media %}
      <li>
        <label>
          <input type="checkbox" name="remove_session_media" value="{{ sm.id }}">
          Remove
        </label>
        <span>{{ sm.media_file.original_filename or sm.media_file.file_key }} ({{ sm.media_file.media_type }})</span>
      </li>
    {% endfor %}
  </ul>
</fieldset>
{% endif %}

{# Add new media #}
<fieldset class="form-row media-uploads">
  <legend>{{ "add_media" | ui }}</legend>
  <div class="form-row">
    <label for="photos">{{ "photos_label" | ui }}</label>
    <input type="file" id="photos" name="photos" multiple accept="image/jpeg,image/png,image/webp">
  </div>
  <div class="form-row">
    <label for="audios">{{ "audio_label" | ui }}</label>
    <input type="file" id="audios" name="audios" multiple accept="audio/mpeg,audio/wav,audio/mp4,audio/x-m4a">
  </div>
  <div class="form-row">
    <label for="videos">{{ "videos_label" | ui }}</label>
    <input type="file" id="videos" name="videos" multiple accept="video/mp4,video/webm,video/quicktime">
  </div>
</fieldset>
```

Also: the `<form method="post" ...>` must include `enctype="multipart/form-data"` — update both `sessions/new.html` and `sessions/edit.html`:

```jinja
<form method="post" action="..." class="session-form" enctype="multipart/form-data">
```

In `flexlog/templates/_partials/link_row_form.html`, add a thumbnail input row after the existing fields:

```jinja
{# Thumbnail input — file picker if no existing thumbnail; clear checkbox if existing #}
{% if link.get('thumbnail_media_id') %}
  <span class="link-thumb-existing">[thumbnail set]</span>
  <label><input type="checkbox" name="clear_link_thumbnail" value="{{ link.id }}"> Clear</label>
{% endif %}
<input type="file" name="link_thumbnail" accept="image/jpeg,image/png,image/webp" class="link-thumbnail-input">
```

Note: the existing `link_row_form.html` doesn't always have access to `link.id` (e.g., a brand-new row added via JS doesn't have one). The clear-thumbnail checkbox only renders for existing rows.

Add an integration test that verifies the form renders the file inputs:

```python
def test_session_form_includes_file_inputs(client, db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    resp = client.get(f"/people/{p.id}/sessions/new")
    body = resp.get_data(as_text=True)
    assert 'name="photos"' in body
    assert 'name="audios"' in body
    assert 'name="videos"' in body
    assert 'multipart/form-data' in body
    assert 'name="link_thumbnail"' in body
```

(Add to `tests/integration/test_session_routes.py`.)

Run pytest. Commit:

```bash
git add flexlog/templates/sessions/_form_body.html \
        flexlog/templates/sessions/new.html \
        flexlog/templates/sessions/edit.html \
        flexlog/templates/_partials/link_row_form.html \
        flexlog/web/sessions_bp.py \
        tests/integration/test_session_routes.py
git commit -m "M4: add file inputs + remove-media checkboxes to session form"
```

---

## Task 7: Session detail — render audio + video + photo grid + link thumbnails

**Files:**
- Modify: `flexlog/templates/sessions/detail.html`
- Modify: `flexlog/templates/_partials/link_row_display.html`
- Create: `flexlog/templates/_partials/media_audio.html`
- Create: `flexlog/templates/_partials/media_video.html`
- Create: `flexlog/templates/_partials/media_photo_thumb.html`
- Modify: `flexlog/web/sessions_bp.py:detail` — pass photos / audios / videos lists separately

In `web/sessions_bp.py:detail`, replace the body to compute media slices:

```python
@sessions_bp.get("/sessions/<session_id>")
def detail(session_id: str):
    s = _session_or_404(session_id)
    enabled_ids = [d.id for d in _enabled_rating_dimensions()]
    current, archived = split_custom_ratings(s.custom_ratings_json, enabled_ids)
    label_map = {d.id: d.label for d in _enabled_rating_dimensions()}
    current_with_labels = [(rid, label_map[rid], val) for rid, val in current]
    photos = [j.media_file for j in s.media_joins if j.media_file.media_type == "photo"]
    audios = [j.media_file for j in s.media_joins if j.media_file.media_type == "audio"]
    videos = [j.media_file for j in s.media_joins if j.media_file.media_type == "video"]
    return render_template(
        "sessions/detail.html",
        person=s.person, session=s,
        current_ratings=current_with_labels,
        archived_ratings=archived,
        photos=photos, audios=audios, videos=videos,
    )
```

Create `flexlog/templates/_partials/media_audio.html`:

```jinja
<li class="audio-item">
  <audio controls preload="metadata" src="{{ url_for('media.serve', file_key=media.file_key) }}"></audio>
  <span class="audio-name">{{ media.original_filename or media.file_key }}</span>
  <a class="audio-download" href="{{ url_for('media.serve', file_key=media.file_key) }}" download="{{ media.original_filename or '' }}">Download</a>
</li>
```

Create `flexlog/templates/_partials/media_video.html`:

```jinja
<li class="video-item">
  <video controls preload="metadata" src="{{ url_for('media.serve', file_key=media.file_key) }}"></video>
  <span class="video-name">{{ media.original_filename or media.file_key }}</span>
</li>
```

Create `flexlog/templates/_partials/media_photo_thumb.html`:

```jinja
{# Inside a PhotoSwipe gallery container: each anchor opens the lightbox. #}
{# data-pswp-width and data-pswp-height are unknown for now (we don't decode #}
{# the image server-side). PhotoSwipe accepts 'auto' but most reliably uses #}
{# real values; M5 polish can add server-side image dimensions if desired. #}
<a class="photo-thumb"
   href="{{ url_for('media.serve', file_key=media.file_key) }}"
   data-pswp-width="1600"
   data-pswp-height="1200"
   target="_blank"
   rel="noopener noreferrer">
  <img src="{{ url_for('media.serve', file_key=media.file_key) }}" alt="{{ media.original_filename or '' }}" loading="lazy">
</a>
```

In `flexlog/templates/sessions/detail.html`, add new sections after the notes section and before the links section:

```jinja
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
```

At the END of `sessions/detail.html`, before `{% endblock %}`:

```jinja
<link rel="stylesheet" href="{{ url_for('static', filename='vendor/photoswipe/photoswipe.css') }}">
<script type="module" src="{{ url_for('static', filename='js/photoswipe_init.js') }}"></script>
```

(PhotoSwipe v5 uses ES modules. The init script imports from the vendored UMD files; if module imports prove finicky, fall back to a plain `<script defer src="...umd.min.js">` and a non-module init. Task 8 spec'd module ESM works in modern browsers per PhotoSwipe docs.)

In `_partials/link_row_display.html`, add a thumbnail beside the link if present:

```jinja
<li class="link-display">
  {% if link.thumbnail_media_id %}
    {# Look up the file via a Jinja test helper isn't trivial; instead the #}
    {# detail view should pre-resolve thumbnails. Simpler: assume the route #}
    {# attaches link.thumbnail (the MediaFile relationship). For M4, since #}
    {# we didn't add SQLAlchemy relationship() between SessionLink and #}
    {# MediaFile, the route looks them up explicitly. To keep the template #}
    {# simple, the route passes a dict link_thumbnails: {link_id: MediaFile}. #}
    {% if link_thumbnails and link.id in link_thumbnails %}
      <img class="link-thumb-image"
           src="{{ url_for('media.serve', file_key=link_thumbnails[link.id].file_key) }}"
           alt=""
           loading="lazy">
    {% endif %}
  {% endif %}
  <a href="{{ link.url }}" target="_blank" rel="noopener noreferrer">
    {{ link.label or link.url }}
  </a>
  {% if link.label %}<span class="link-url-meta">{{ link.url }}</span>{% endif %}
</li>
```

Update the route to compute the thumbnail dict:

```python
    # build link_thumbnails: {link.id: MediaFile} for the template
    link_thumbnails = {}
    for link in s.links:
        if link.thumbnail_media_id:
            mf = db.get(MediaFile, link.thumbnail_media_id)  # need MediaFile import
            if mf is not None:
                link_thumbnails[link.id] = mf
```

(Pass `link_thumbnails=link_thumbnails` into the template render context.)

Add tests to `tests/integration/test_session_with_media.py`:

```python
def test_detail_renders_audio_player(client, db_session):
    import io
    from werkzeug.datastructures import FileStorage
    p = _person(db_session)
    # Inline upload so we can assert specific markup
    MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "audios": (io.BytesIO(MP3), "x.mp3", "audio/mpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import Session as SR
    sid = db_session.query(SR).first().id
    resp = client.get(f"/sessions/{sid}")
    body = resp.get_data(as_text=True)
    assert "<audio" in body
    assert "controls" in body


def test_detail_renders_photo_gallery(client, db_session):
    p = _person(db_session)
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG_BYTES), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    from flexlog.db.models import Session as SR
    sid = db_session.query(SR).first().id
    resp = client.get(f"/sessions/{sid}")
    body = resp.get_data(as_text=True)
    assert "photo-grid" in body
    assert "data-pswp-width" in body
    assert "/media/" in body  # serve URL
```

Commit:

```bash
git add flexlog/templates/sessions/detail.html \
        flexlog/templates/_partials/media_audio.html \
        flexlog/templates/_partials/media_video.html \
        flexlog/templates/_partials/media_photo_thumb.html \
        flexlog/templates/_partials/link_row_display.html \
        flexlog/web/sessions_bp.py tests/integration/test_session_with_media.py
git commit -m "M4: render audio/video players + photo gallery on session detail

PhotoSwipe-friendly anchor markup with data-pswp-width/height on each
photo thumb. Inline <audio>/<video> with controls + preload=metadata.
Link thumbnails render alongside link rows when set."
```

---

## Task 8: Vendor PhotoSwipe + photo lightbox init

**Files:**
- Create: `flexlog/static/vendor/photoswipe/photoswipe.css`
- Create: `flexlog/static/vendor/photoswipe/photoswipe.umd.min.js`
- Create: `flexlog/static/vendor/photoswipe/photoswipe-lightbox.umd.min.js`
- Create: `flexlog/static/js/photoswipe_init.js`

- [ ] **Step 8.1: Vendor PhotoSwipe v5.4.4**

Run from the project root:

```bash
mkdir -p flexlog/static/vendor/photoswipe
curl -L -o flexlog/static/vendor/photoswipe/photoswipe.css \
  https://cdn.jsdelivr.net/npm/photoswipe@5.4.4/dist/photoswipe.css
curl -L -o flexlog/static/vendor/photoswipe/photoswipe.umd.min.js \
  https://cdn.jsdelivr.net/npm/photoswipe@5.4.4/dist/umd/photoswipe.umd.min.js
curl -L -o flexlog/static/vendor/photoswipe/photoswipe-lightbox.umd.min.js \
  https://cdn.jsdelivr.net/npm/photoswipe@5.4.4/dist/umd/photoswipe-lightbox.umd.min.js
```

Verify file sizes are non-zero (a few hundred KB total).

- [ ] **Step 8.2: Implement `flexlog/static/js/photoswipe_init.js`**

Use the UMD build (not module) so the init script works without ES module wiring. Switch the detail template's script tag from `type="module"` to a plain script:

```javascript
// Initialize PhotoSwipe on every session detail page.
// PhotoSwipeLightbox auto-discovers anchors matching the gallery selector.

(function () {
  "use strict";
  const gallery = document.getElementById("photo-gallery");
  if (!gallery || typeof PhotoSwipeLightbox === "undefined") return;

  const lightbox = new PhotoSwipeLightbox({
    gallery: "#photo-gallery",
    children: "a.photo-thumb",
    pswpModule: PhotoSwipe,
  });
  lightbox.init();
})();
```

Update `sessions/detail.html` script tags to load PhotoSwipe globals:

```jinja
<link rel="stylesheet" href="{{ url_for('static', filename='vendor/photoswipe/photoswipe.css') }}">
<script src="{{ url_for('static', filename='vendor/photoswipe/photoswipe.umd.min.js') }}" defer></script>
<script src="{{ url_for('static', filename='vendor/photoswipe/photoswipe-lightbox.umd.min.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/photoswipe_init.js') }}" defer></script>
```

The UMD builds expose `window.PhotoSwipe` and `window.PhotoSwipeLightbox`; passing them into the lightbox constructor wires it up.

- [ ] **Step 8.3: Run pytest + commit**

```bash
git add flexlog/static/vendor/photoswipe/ flexlog/static/js/photoswipe_init.js flexlog/templates/sessions/detail.html
git commit -m "M4: vendor PhotoSwipe v5.4.4 + photo lightbox init"
```

---

## Task 9: Library blueprint — list + filters + hard-delete + soft-unlink-from-session

**Files:**
- Create: `flexlog/web/library_bp.py`
- Modify: `flexlog/web/__init__.py`
- Create: `tests/integration/test_library_routes.py`

- [ ] **Step 9.1: Implement `flexlog/web/library_bp.py`**

```python
"""Media Library routes."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from flexlog.db import get_db
from flexlog.services.library import (
    MediaNotFoundError,
    hard_delete,
    list_library,
)
from flexlog.services.media import unlink_from_session

library_bp = Blueprint("library", __name__)


_VALID_TYPES = {"photo", "audio", "video"}


@library_bp.get("/library")
def index():
    media_type = request.args.get("type") or None
    if media_type not in _VALID_TYPES and media_type is not None:
        media_type = None
    orphans_only = request.args.get("orphans") == "1"
    rows = list_library(get_db(), media_type=media_type, orphans_only=orphans_only)
    return render_template(
        "library/index.html",
        rows=rows,
        active_type=media_type,
        orphans_only=orphans_only,
    )


@library_bp.post("/library/<media_file_id>/hard_delete")
def hard_delete_route(media_file_id: str):
    db = get_db()
    try:
        hard_delete(db, media_file_id)
    except MediaNotFoundError:
        abort(404)
    db.commit()
    flash("Deleted.", "success")
    return redirect(url_for("library.index"))


@library_bp.post("/sessions/<session_id>/media/<session_media_id>/unlink")
def unlink_from_session_route(session_id: str, session_media_id: str):
    """Soft-unlink: remove the session_media join. File stays on disk."""
    db = get_db()
    unlink_from_session(db, session_media_id)
    db.commit()
    return redirect(url_for("sessions.edit", session_id=session_id))
```

Register in `flexlog/web/__init__.py`:

```python
from flexlog.web.library_bp import library_bp
...
def register_blueprints(app):
    ...
    app.register_blueprint(library_bp)
```

- [ ] **Step 9.2: Tests**

`tests/integration/test_library_routes.py`:

```python
import io

from werkzeug.datastructures import FileStorage


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 100


def _upload(client, db_session, name="x.jpg", data=JPEG, mime="image/jpeg"):
    from flexlog.services.media import upload_to_media_file
    fs = FileStorage(stream=io.BytesIO(data), filename=name, content_type=mime)
    # Need an app context — use the test client's transaction-scoped app
    from flask import current_app
    # The fixture's `app` is implicitly used; do via direct service in db_session
    with db_session.bind.engine.connect():
        pass
    # Simplest: do it by hitting the upload-via-session route. But we want to
    # write standalone library tests. Let's use the service directly inside
    # the test app's context.
    raise RuntimeError("use the upload helper from test_session_with_media if needed")


def test_library_index_empty(client):
    resp = client.get("/library")
    assert resp.status_code == 200


def test_library_index_lists_uploaded_files(client, db_session, app):
    """Upload via session route, then assert /library shows the row."""
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    resp = client.get("/library")
    body = resp.get_data(as_text=True)
    assert "x.jpg" in body  # original filename rendered


def test_library_filter_by_type(client, db_session, app):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 100
    client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15", "overall_score": "4",
            "photos": (io.BytesIO(JPEG), "p.jpg", "image/jpeg"),
            "audios": (io.BytesIO(MP3), "a.mp3", "audio/mpeg"),
        },
        content_type="multipart/form-data",
    )
    resp_photos = client.get("/library?type=photo").get_data(as_text=True)
    assert "p.jpg" in resp_photos and "a.mp3" not in resp_photos
    resp_audios = client.get("/library?type=audio").get_data(as_text=True)
    assert "a.mp3" in resp_audios and "p.jpg" not in resp_audios


def test_library_orphan_filter(client, db_session, app):
    """Files referenced by a session disappear when filtered to orphans only."""
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "linked.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    resp = client.get("/library?orphans=1").get_data(as_text=True)
    assert "linked.jpg" not in resp


def test_library_hard_delete_removes_file(client, db_session, app):
    from flexlog import paths
    from flexlog.db.models import MediaFile
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4", "photos": (io.BytesIO(JPEG), "x.jpg", "image/jpeg")},
        content_type="multipart/form-data",
    )
    db_session.expire_all()
    mf = db_session.query(MediaFile).first()
    target = paths.resolve_file_key(mf.file_key)
    assert target.exists()
    client.post(f"/library/{mf.id}/hard_delete", follow_redirects=False)
    db_session.expire_all()
    assert db_session.get(MediaFile, mf.id) is None
    assert not target.exists()


def test_library_hard_delete_404(client):
    resp = client.post("/library/nope/hard_delete")
    assert resp.status_code == 404
```

- [ ] **Step 9.3: Commit**

```bash
git add flexlog/web/library_bp.py flexlog/web/__init__.py tests/integration/test_library_routes.py
git commit -m "M4: add Media Library routes — list, filter, hard-delete

GET /library lists every media_file with reference count; ?type=photo|audio|video
filters by type; ?orphans=1 shows only unreferenced files. POST
/library/<id>/hard_delete fires hard_delete which cascades through
session_media (FK) and SET NULLs avatar + thumbnail FKs, then deletes
the disk file via after-commit event."
```

---

## Task 10: Library template + nav link

**Files:**
- Create: `flexlog/templates/library/index.html`
- Create: `flexlog/templates/library/_partials/media_tile.html`
- Modify: `flexlog/templates/_base.html` (add nav link to /library)
- Modify: `flexlog/web/filters.py` (extend BUILTIN_UI_DEFAULTS)

In `filters.py` BUILTIN_UI_DEFAULTS add:

```python
    "media_library": "Media Library",
    "photos_label": "Photos",
    "audio_label": "Audio",
    "videos_label": "Videos",
    "add_media": "Add media",
    "remove_media": "Remove",
    "filter_all": "All",
    "filter_orphans": "Orphans only",
    "references_one": "ref",
    "references_many": "refs",
    "hard_delete_warning": "This permanently deletes the file from disk and removes all references. Cannot be undone.",
    "delete_button": "Delete",
```

Update `_base.html` nav (find the existing `<nav class="site-nav">` block):

```jinja
<nav class="site-nav">
  <a href="{{ url_for('home.home') }}">{{ labels.entity.plural }}</a>
  <a href="{{ url_for('library.index') }}">{{ "media_library" | ui }}</a>
</nav>
```

Create `flexlog/templates/library/index.html`:

```jinja
{% extends "_base.html" %}

{% block title %}{{ "media_library" | ui }} — {{ labels.app_name }}{% endblock %}

{% block content %}
<section class="library">
  <header class="library-header">
    <h2>{{ "media_library" | ui }}</h2>
    <nav class="library-filters">
      <a class="filter-tab {% if not active_type %}active{% endif %}" href="{{ url_for('library.index', orphans=('1' if orphans_only else None)) }}">{{ "filter_all" | ui }}</a>
      <a class="filter-tab {% if active_type == 'photo' %}active{% endif %}" href="{{ url_for('library.index', type='photo', orphans=('1' if orphans_only else None)) }}">{{ "photos_label" | ui }}</a>
      <a class="filter-tab {% if active_type == 'audio' %}active{% endif %}" href="{{ url_for('library.index', type='audio', orphans=('1' if orphans_only else None)) }}">{{ "audio_label" | ui }}</a>
      <a class="filter-tab {% if active_type == 'video' %}active{% endif %}" href="{{ url_for('library.index', type='video', orphans=('1' if orphans_only else None)) }}">{{ "videos_label" | ui }}</a>
      <label class="orphans-toggle">
        <input type="checkbox" {% if orphans_only %}checked{% endif %} onchange="window.location='{{ url_for('library.index', type=active_type) }}' + (this.checked ? '?orphans=1' : '')">
        {{ "filter_orphans" | ui }}
      </label>
    </nav>
  </header>

  {% if rows %}
    <ul class="library-grid">
      {% for row in rows %}
        <li>{% include "library/_partials/media_tile.html" %}</li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="empty-state">{{ "empty_dashboard" | ui }}</p>
  {% endif %}
</section>
{% endblock %}
```

Create `flexlog/templates/library/_partials/media_tile.html`:

```jinja
<article class="library-tile {% if row.is_orphan %}is-orphan{% endif %}">
  <div class="library-tile-media">
    {% if row.media_file.media_type == 'photo' %}
      <img src="{{ url_for('media.serve', file_key=row.media_file.file_key) }}" alt="{{ row.media_file.original_filename or '' }}" loading="lazy">
    {% elif row.media_file.media_type == 'audio' %}
      <span class="library-icon" aria-hidden="true">♪</span>
    {% elif row.media_file.media_type == 'video' %}
      <span class="library-icon" aria-hidden="true">▶</span>
    {% endif %}
  </div>
  <div class="library-tile-meta">
    <p class="library-tile-name">{{ row.media_file.original_filename or row.media_file.file_key }}</p>
    <p class="library-tile-info">
      {{ row.media_file.media_type }} ·
      {{ "%.0f"|format(row.media_file.file_size_bytes / 1024) }} KB ·
      {{ row.total_refs }} {{ "references_one" | ui if row.total_refs == 1 else "references_many" | ui }}
      {% if row.is_orphan %}<span class="orphan-badge">orphan</span>{% endif %}
    </p>
  </div>
  <form method="post" action="{{ url_for('library.hard_delete_route', media_file_id=row.media_file.id) }}" onsubmit="return confirm('{{ "hard_delete_warning" | ui }}');">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <button type="submit" class="btn btn-danger">{{ "delete_button" | ui }}</button>
  </form>
</article>
```

Add a test to `tests/integration/test_library_routes.py`:

```python
def test_library_nav_link_in_base_template(client):
    resp = client.get("/")
    assert "/library" in resp.get_data(as_text=True)
```

Commit:

```bash
git add flexlog/templates/library/ flexlog/templates/_base.html flexlog/web/filters.py tests/integration/test_library_routes.py
git commit -m "M4: add Media Library page + nav link"
```

---

## Task 11: CSS for media + library + cleanup tmp files at startup

**Files:**
- Modify: `flexlog/static/css/main.css`
- Modify: `flexlog/app.py` (sweep `uploads/.tmp/` of stale files at startup; set MAX_CONTENT_LENGTH)

In `flexlog/app.py`, inside `create_app()` after `paths.ensure_layout()`:

```python
    # Sweep stale uploads/.tmp/ files (>1 hour old) on startup per spec §4.3.
    import time
    tmp_dir = paths.tmp_uploads_dir()
    cutoff = time.time() - 3600
    for entry in tmp_dir.iterdir() if tmp_dir.exists() else []:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
        except OSError:
            pass

    # Allow up to 3 GiB request body so 500 MB files × multiple uploads work.
    # Per-file size is enforced server-side in services/media.py.
    app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024 * 1024
```

CSS additions to `main.css`:

```css
/* M4 — media + library */

.media-section {
  margin: 1.5rem 0;
}
.audio-list, .video-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.audio-item, .video-item {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.audio-item audio { width: 100%; max-width: 600px; }
.video-item video { width: 100%; max-width: 800px; border-radius: 6px; }
.audio-name, .video-name { color: var(--muted); font-size: 0.9rem; }

.photo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.5rem;
}
.photo-thumb {
  display: block;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border-radius: 6px;
  border: 1px solid var(--border);
}
.photo-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.15s ease;
}
.photo-thumb:hover img { transform: scale(1.04); }

.link-thumb-image {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  vertical-align: middle;
  margin-right: 0.5rem;
}

/* Library */
.library-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}
.library-filters {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.filter-tab {
  text-decoration: none;
  color: var(--muted);
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
}
.filter-tab.active {
  color: var(--fg);
  background: var(--bg-soft);
}
.orphans-toggle {
  font-size: 0.9rem;
  color: var(--muted);
}

.library-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1rem;
}
.library-tile {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.library-tile.is-orphan { border-color: #fcd34d; background: #fffbeb; }
.library-tile-media {
  aspect-ratio: 4 / 3;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-soft);
}
.library-tile-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.library-icon {
  font-size: 2.5rem;
  color: var(--muted);
}
.library-tile-meta {
  padding: 0.5rem;
}
.library-tile-name {
  margin: 0;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.library-tile-info {
  margin: 0.25rem 0;
  font-size: 0.85rem;
  color: var(--muted);
}
.orphan-badge {
  display: inline-block;
  padding: 0 0.25rem;
  background: #fcd34d;
  color: #78350f;
  border-radius: 4px;
  font-size: 0.75rem;
  margin-left: 0.5rem;
}
.library-tile form {
  padding: 0.5rem;
  border-top: 1px solid var(--border);
}
```

Commit:

```bash
git add flexlog/static/css/main.css flexlog/app.py
git commit -m "M4: media + library CSS; tmp sweep + MAX_CONTENT_LENGTH at startup"
```

---

## Task 12: Final sweep — README + smoke + tag

- [ ] Update `README.md`:

Replace "Features (M3)" with "Features (M4)" listing the new media features. Update "What's next" to mark M4 as shipped, M5 as upcoming.

```markdown
## Features (M4)

- Add, edit, delete people; global tags; dashboard with search + per-person aggregates
- Sessions with date, score, custom rating dimensions, notes, links
- **Media uploads (M4):** attach photos / audio / video to a session; multiple files per type; SHA-256 dedup means uploading the same bytes twice produces only one file on disk
- **Inline playback:** audio + video play in the page; photos open in a PhotoSwipe lightbox carousel
- **Link thumbnails:** each session link can carry a user-uploaded thumbnail image
- **Media Library** at `/library` listing every uploaded file with type filter, orphans-only filter, and hard-delete (only place that removes a file from disk)
- Default avatar placeholder (real avatar upload comes in M5)
```

```markdown
## What's next

- **M2 (✓ shipped):** people + tags + dashboard
- **M3 (✓ shipped):** sessions + ratings + notes + dashboard aggregates
- **M4 (✓ shipped):** media + Media Library + hash dedup
- M5: avatar cropper + sort + polish
```

- [ ] Run `make test`. Expect 350+ tests, ≥85% coverage.
- [ ] Run `make smoke`. Expect 3 OK lines.
- [ ] Manual end-to-end: start `flexlog`, create a person, create a session, upload a photo + an audio file, view the session detail (lightbox should open), check `/library`, hard-delete a file, verify it's gone from disk.
- [ ] Commit + tag:

```bash
git add README.md
git commit -m "M4: update README with media features and roadmap"
git tag m4-media
```

---

## Self-review notes

**Spec coverage:**

| Spec section | Implemented in |
|---|---|
| §4 storage layout (content-addressed) | Task 2 — `services/media.py` |
| §4.3 upload pipeline | Task 2 |
| §4.4 MIME → ext matrix | paths.py (M1) + Task 2 magic-byte check |
| §5 retention model (soft-unlink + hard delete) | Tasks 3, 5, 9 |
| §6.8 Session Detail with media | Task 7 |
| §6.9 Add/Edit Session multipart | Tasks 5, 6 |
| §7 media_file, session_media schema + FKs | Task 1 |
| §8 routes /media, /library, /sessions/<id>/media/<id>/unlink | Tasks 4, 9 |
| §11 testing | throughout |
| §12 M4 deliverable | all |

**PRD deviations now exercised** (from spec §13):
- Disk layout content-addressed (not per-session) — Tasks 1, 2
- Soft-unlink + Media Library hard-delete (not hard-cascade) — Tasks 3, 5, 9

**Boundary discipline:** No avatar cropper UI (M5). No dashboard sort options (M5). No PDF export (post-MVP).

---

**End of M4 plan.**
