# flexlog M2 People + Tags — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first domain entities (people + global tags), full Person CRUD, the dashboard people-list with search and tag chips, and the person-detail page (with an empty-session-list placeholder until M3). Wire SQLAlchemy + Flask-WTF into the M1 foundation; CSRF-protect every mutating form; persist a per-install secret key.

**Architecture:** Plug into M1's app factory between data-dir validation and blueprint registration: open a SQLAlchemy engine on `paths.db_path()`, run `Base.metadata.create_all()`, register a teardown that closes per-request sessions. Add a Flask-WTF `CSRFProtect`. Tags are global, deduped by `slug` (unicode-lowercased + non-alnum collapsed to `-`). Person CRUD goes through `services/people.py`; tags are managed via `services/tags.py`. Avatar upload is **not** in M2 — every avatar slot renders a default placeholder. M3 will fill in session aggregates; M2 leaves dashboard "session count / last session / avg score" columns out of the dashboard card entirely (they appear in M3).

**Tech Stack:** Python 3.11+, Flask 3.x, **SQLAlchemy 2.x ORM (new)**, **Flask-WTF (new)**, Jinja2, pytest, pytest-cov. No Alembic.

**Source spec:** `docs/superpowers/specs/2026-05-07-flexlog-design.md` — §6.5 Dashboard, §6.6 Person Detail, §6.7 Add/Edit Person, §6.10 Delete Behavior (reinterpreted: M2 has no media to unlink), §7 Data model, §8 Routes, §9 Security, §12 M2 deliverable.

**M2 deliverable:** From a fresh `FLEXLOG_DATA_DIR`, `flexlog` starts, `encounters.db` is created with `person`/`tag`/`person_tag` tables, the dashboard at `/` shows the empty state, and the user can:
- create a person (alias required, optional comma-separated tags)
- view the person's detail page (with default avatar + alias + tag chips + "no sessions yet")
- edit the person (rename, retag)
- delete the person via type-the-alias confirmation
- search the dashboard by alias or tag
- everything is CSRF-protected; XSS attempts in alias/tags are rendered as text

---

## File structure

| Path | Purpose |
|---|---|
| `pyproject.toml` | Add `SQLAlchemy>=2.0,<3.0` + `Flask-WTF>=1.2,<2.0` to deps |
| `flexlog/secret_key.py` | `load_or_create_secret_key()` — reads `$FLEXLOG_DATA_DIR/.secret_key` (mode 0600), creates on first run with `secrets.token_hex(32)` |
| `flexlog/db/__init__.py` | `Base`, `engine_for(db_path)`, `session_factory_for(engine)`, request-scoped session helpers |
| `flexlog/db/models.py` | SQLAlchemy declarative models: `Person`, `Tag`, `PersonTag`, indexes |
| `flexlog/services/__init__.py` | Empty marker |
| `flexlog/services/tags.py` | `slugify()`, `normalize_tag_input()`, `get_or_create_tag()`, `list_all_tags()` |
| `flexlog/services/people.py` | `create_person()`, `get_person()`, `list_people()`, `search_people()`, `update_person()`, `delete_person()`, dashboard query |
| `flexlog/web/forms.py` | `PersonForm` (alias required; tags free-text comma-separated) |
| `flexlog/web/people_bp.py` | All `/people/...` routes |
| `flexlog/web/dashboard_bp.py` | `GET /` dashboard with search + people grid (replaces M1 `home_bp`) |
| `flexlog/web/__init__.py` | Update registry: drop `home_bp`, register `dashboard_bp` + `people_bp` |
| `flexlog/web/filters.py` | Extend `BUILTIN_UI_DEFAULTS` with M2 keys (`edit_person`, `delete_person`, `delete_person_confirm_prompt`, `add_session_disabled`, `tags_label`, `untagged`) |
| `flexlog/app.py` | Wire `secret_key`, `CSRFProtect`, DB engine + teardown |
| `flexlog/templates/dashboard.html` | Replaces `home.html` — list of people with search + empty state |
| `flexlog/templates/people/new.html` | Add Person form |
| `flexlog/templates/people/edit.html` | Edit Person form |
| `flexlog/templates/people/detail.html` | Person Detail (no sessions in M2; placeholder list) |
| `flexlog/templates/_partials/person_card.html` | Reusable card for dashboard rows |
| `flexlog/templates/_partials/tag_chip.html` | Reusable tag chip |
| `flexlog/templates/_partials/avatar_placeholder.html` | Default circular avatar (initials from alias) |
| `flexlog/templates/home.html` | **Delete** (replaced by `dashboard.html`) |
| `flexlog/static/css/main.css` | Append rules for `.person-grid`, `.person-card`, `.tag-chip`, `.avatar-placeholder`, form layouts |
| `flexlog/static/js/people_form.js` | Tag-chip preview UX (parse comma-separated input → render chips) |
| `tests/conftest.py` | Update: `app` fixture sets `WTF_CSRF_ENABLED=False`; add `db_session` fixture; add `csrf_app`/`csrf_client` for the one CSRF test |
| `tests/unit/test_secret_key.py` | Generate-on-first-run; reuse-existing; mode 0600; rejects 0644 |
| `tests/unit/test_tags_service.py` | `slugify`, `normalize_tag_input`, `get_or_create_tag`, dedup |
| `tests/unit/test_people_service.py` | CRUD + search behavior, isolated from routes |
| `tests/integration/test_app_factory.py` | Update for DB wiring + secret_key + CSRF setup |
| `tests/integration/test_dashboard.py` | Empty state, list rendering, search filters, tag chips |
| `tests/integration/test_people_routes.py` | New/Create/Edit/Update/Detail flows + XSS safety |
| `tests/integration/test_people_delete.py` | Type-alias-to-confirm; wrong alias rejected |
| `tests/integration/test_csrf.py` | One end-to-end test that POST without token → 400 |

---

## Task 1: Add SQLAlchemy + Flask-WTF deps + create empty db/services/web packages

**Files:**
- Modify: `pyproject.toml`
- Create: `flexlog/db/__init__.py` (placeholder)
- Create: `flexlog/services/__init__.py` (empty)

- [ ] **Step 1.1: Update `pyproject.toml`**

Update only the `[project] dependencies` block:

```toml
dependencies = [
    "Flask>=3.0,<4.0",
    "SQLAlchemy>=2.0,<3.0",
    "Flask-WTF>=1.2,<2.0",
]
```

Leave the rest of the file unchanged.

- [ ] **Step 1.2: Reinstall deps**

```bash
source .venv/bin/activate
pip install -e ".[dev]"
```

Confirm `python -c "import sqlalchemy; import flask_wtf; print(sqlalchemy.__version__, flask_wtf.__version__)"` prints non-error output with SQLAlchemy ≥2.0 and Flask-WTF ≥1.2.

- [ ] **Step 1.3: Create `flexlog/db/__init__.py` placeholder**

```python
"""Database engine + session factory for flexlog.

Models live in flexlog.db.models. The engine is created from
flexlog.paths.db_path() at app-factory time; session lifecycle is
request-scoped via Flask's `g` object and the teardown handler.
"""
```

- [ ] **Step 1.4: Create `flexlog/services/__init__.py` (empty)**

Empty marker file.

- [ ] **Step 1.5: Run pytest — coverage gate must stay green**

```bash
pytest -v
```

Expected: 91 tests still pass; coverage ≥85%. (No code changes that affect existing modules; new files contribute zero statements.)

- [ ] **Step 1.6: Commit**

```bash
git add pyproject.toml flexlog/db/__init__.py flexlog/services/__init__.py
git commit -m "M2: add SQLAlchemy + Flask-WTF deps; scaffold db/services packages"
```

---

## Task 2: `flexlog/secret_key.py` — load-or-create with mode 0600

CSRF needs a Flask `SECRET_KEY`. Per spec §9 it's persisted to `$FLEXLOG_DATA_DIR/.secret_key` with mode 0600 and generated on first run with `secrets.token_hex(32)`.

**Files:**
- Create: `flexlog/secret_key.py`
- Create: `tests/unit/test_secret_key.py`

- [ ] **Step 2.1: Write the failing tests**

`tests/unit/test_secret_key.py`:

```python
import os
import stat
from pathlib import Path

import pytest

from flexlog.secret_key import (
    SecretKeyError,
    load_or_create_secret_key,
)


def test_load_or_create_creates_when_missing(tmp_path):
    key_file = tmp_path / ".secret_key"
    assert not key_file.exists()
    secret = load_or_create_secret_key(key_file)
    assert isinstance(secret, str)
    assert len(secret) >= 32  # token_hex(32) = 64 hex chars
    assert key_file.exists()
    # Permissions are 0600
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_load_or_create_reuses_existing(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("existing-secret-value")
    key_file.chmod(0o600)
    got = load_or_create_secret_key(key_file)
    assert got == "existing-secret-value"


def test_load_or_create_rejects_world_readable(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("leaky-secret")
    key_file.chmod(0o644)  # group + world readable
    with pytest.raises(SecretKeyError, match="permissions"):
        load_or_create_secret_key(key_file)


def test_load_or_create_rejects_empty_file(tmp_path):
    key_file = tmp_path / ".secret_key"
    key_file.write_text("")
    key_file.chmod(0o600)
    with pytest.raises(SecretKeyError, match="empty"):
        load_or_create_secret_key(key_file)


def test_load_or_create_strips_trailing_newline(tmp_path):
    """A user editing the file may leave a newline; tolerate it."""
    key_file = tmp_path / ".secret_key"
    key_file.write_text("user-edited-secret\n")
    key_file.chmod(0o600)
    got = load_or_create_secret_key(key_file)
    assert got == "user-edited-secret"


def test_two_invocations_yield_same_secret(tmp_path):
    """First call generates; second call reads what the first wrote."""
    key_file = tmp_path / ".secret_key"
    first = load_or_create_secret_key(key_file)
    second = load_or_create_secret_key(key_file)
    assert first == second


def test_generated_secrets_are_unique_per_directory(tmp_path):
    a = load_or_create_secret_key(tmp_path / "a.key")
    b = load_or_create_secret_key(tmp_path / "b.key")
    assert a != b
```

- [ ] **Step 2.2: Run failing tests**

```bash
pytest tests/unit/test_secret_key.py -v
```

Expected: ImportError on missing module.

- [ ] **Step 2.3: Implement `flexlog/secret_key.py`**

```python
"""Load or generate the Flask SECRET_KEY for CSRF + session signing.

The key lives at $FLEXLOG_DATA_DIR/.secret_key with mode 0600. On first run
flexlog generates 32 random bytes (hex-encoded) and writes the file. On
subsequent runs the existing key is reused so CSRF tokens remain valid
across restarts.

This module is intentionally tiny: a single function with hard guards
around file permissions and emptiness. The path is supplied by the caller
(typically flexlog.paths.data_dir() / ".secret_key") so this module has no
dependency on flexlog.paths and can be unit-tested in isolation.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

# Hex token of 32 bytes = 64 chars; plenty for HMAC-SHA256 CSRF tokens.
_KEY_BYTES = 32


class SecretKeyError(RuntimeError):
    """Raised when the secret key file is unusable (bad permissions, empty, etc.)."""


def load_or_create_secret_key(path: Path) -> str:
    """Read the key at `path`, or generate one if missing.

    Hard rules:
      - If the file exists, its mode must be exactly 0600.
      - If the file exists and is empty after stripping whitespace, raise.
      - On generation, the file is written 0600 atomically.
    """
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise SecretKeyError(
                f"secret key file at {path} has permissions {oct(mode)}; expected 0600. "
                "Refusing to load. Run: chmod 600 <path>"
            )
        contents = path.read_text(encoding="utf-8").strip()
        if not contents:
            raise SecretKeyError(f"secret key file at {path} is empty")
        return contents
    # First-run generation
    new_key = secrets.token_hex(_KEY_BYTES)
    # Write atomically via tmp + rename, with 0600 from the start.
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_key)
    except Exception:
        # Best-effort cleanup; do not mask the original error
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise
    os.replace(tmp, path)
    return new_key
```

- [ ] **Step 2.4: Run tests, verify pass**

```bash
pytest -v
```

Expected: all 7 new tests pass; total ≥98 tests; coverage gate green.

- [ ] **Step 2.5: Commit**

```bash
git add flexlog/secret_key.py tests/unit/test_secret_key.py
git commit -m "M2: add per-install secret key with strict 0600 permissions

load_or_create_secret_key() reads an existing key (rejecting any mode
other than 0600 and any empty file) or generates a fresh 32-byte hex
secret on first run. Atomic write via tmp+rename."
```

---

## Task 3: `flexlog/db/__init__.py` — engine, session factory, request-scoped helpers

We use SQLAlchemy 2.x ORM with the new declarative API. The engine is created from `paths.db_path()` and uses SQLite with foreign-key enforcement enabled (SQLite disables FKs by default). We expose three callables:

- `Base` — the declarative base for models.
- `make_engine(db_path: Path)` — builds the engine; turns FK enforcement on.
- `make_session_factory(engine)` — returns a session factory.

Plus two request helpers Flask uses:
- `get_db()` — returns the per-request session, lazily created on `flask.g`.
- `close_db(error)` — teardown callback.

**Files:**
- Modify: `flexlog/db/__init__.py` (replace placeholder with full impl)
- Create: `tests/unit/test_db_init.py`

- [ ] **Step 3.1: Write failing tests**

`tests/unit/test_db_init.py`:

```python
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from flexlog.db import Base, make_engine, make_session_factory


def test_make_engine_creates_sqlite_file_lazily(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    # Engine creation does NOT touch the filesystem until a connection opens.
    # But once we connect, the file appears.
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert db_path.exists()


def test_make_engine_enables_foreign_keys(tmp_path):
    """SQLite ignores ON DELETE CASCADE unless PRAGMA foreign_keys=ON."""
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "foreign_keys pragma must be ON"


def test_make_session_factory_yields_working_sessions(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Session = make_session_factory(engine)
    with Session() as session:
        # Sessions can execute trivial queries
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_base_metadata_is_a_metadata_object(tmp_path):
    """Sanity: Base must expose .metadata for create_all() in app factory."""
    assert hasattr(Base, "metadata")
    # Should have a `create_all` callable
    assert callable(Base.metadata.create_all)
```

- [ ] **Step 3.2: Run failing tests**

```bash
pytest tests/unit/test_db_init.py -v
```

Expected: ImportError on `Base`/`make_engine`/`make_session_factory`.

- [ ] **Step 3.3: Replace `flexlog/db/__init__.py` with full implementation**

```python
"""Database engine + session factory for flexlog.

Models live in flexlog.db.models. The engine is created from
flexlog.paths.db_path() at app-factory time; session lifecycle is
request-scoped via Flask's `g` object and the teardown handler.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all flexlog ORM models."""


def make_engine(db_path: Path) -> Engine:
    """Create the SQLite engine pointed at `db_path`.

    Enables foreign-key enforcement (SQLite has it OFF by default, which
    silently breaks ON DELETE CASCADE / SET NULL).
    """
    # `future=True` is the default in SA 2.x; `echo` is off — too noisy for a
    # local app. The thread-check is off because Flask's dev server uses
    # threads but each request gets its own session.
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_fk_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to `engine`. Each `Session()` is independent."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
```

- [ ] **Step 3.4: Run tests, verify pass**

```bash
pytest -v
```

Expected: all 4 new tests pass; gate green.

- [ ] **Step 3.5: Commit**

```bash
git add flexlog/db/__init__.py tests/unit/test_db_init.py
git commit -m "M2: add db engine + session factory with FK enforcement

make_engine() creates a SQLite engine with PRAGMA foreign_keys=ON wired
through SQLAlchemy's connect event so cascades and SET NULL work."
```

---

## Task 4: `flexlog/db/models.py` — Person, Tag, PersonTag

Spec §7 schema (M2 subset — `session`, `session_link`, `media_file`, `session_media` come in M3/M4). Note: the spec includes `person.avatar_media_id` as a nullable FK to `media_file`. M2 has no `media_file` table yet, so we declare the column without the FK and add the constraint in M4 when `media_file` exists. Alternative: use a string column with a comment. We pick the latter — `avatar_media_id Mapped[str | None] = mapped_column(String, nullable=True)` — because adding the FK in M4 only requires a `Column.foreign_keys` decoration on the existing column, no schema change.

**Files:**
- Create: `flexlog/db/models.py`
- Create: `tests/unit/test_db_models.py`

- [ ] **Step 4.1: Write failing tests**

`tests/unit/test_db_models.py`:

```python
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from flexlog.db import Base, make_engine, make_session_factory
from flexlog.db.models import Person, PersonTag, Tag


@pytest.fixture
def session(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s


def test_create_all_registers_three_tables(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    names = set(inspector.get_table_names())
    assert {"person", "tag", "person_tag"} <= names


def test_create_all_is_idempotent(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    Base.metadata.create_all(engine)  # second call must not raise
    inspector = inspect(engine)
    assert "person" in inspector.get_table_names()


def test_can_insert_person(session):
    p = Person(id=str(uuid.uuid4()), alias="Alice", avatar_media_id=None)
    session.add(p)
    session.commit()
    got = session.get(Person, p.id)
    assert got is not None
    assert got.alias == "Alice"
    assert got.avatar_media_id is None
    assert got.created_at is not None
    assert got.updated_at is not None


def test_person_id_is_unique(session):
    p1 = Person(id="dup-id", alias="A")
    p2 = Person(id="dup-id", alias="B")
    session.add(p1)
    session.commit()
    session.add(p2)
    with pytest.raises(IntegrityError):
        session.commit()


def test_can_insert_tag(session):
    t = Tag(id=str(uuid.uuid4()), name="Engineering", slug="engineering")
    session.add(t)
    session.commit()
    got = session.get(Tag, t.id)
    assert got is not None
    assert got.name == "Engineering"
    assert got.slug == "engineering"


def test_tag_slug_is_unique(session):
    a = Tag(id="ta", name="Engineering", slug="engineering")
    b = Tag(id="tb", name="ENGINEERING", slug="engineering")
    session.add(a)
    session.commit()
    session.add(b)
    with pytest.raises(IntegrityError):
        session.commit()


def test_person_tag_join_links_two(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    join = PersonTag(person_id="p1", tag_id="t1")
    session.add(join)
    session.commit()
    rows = session.execute(text("SELECT person_id, tag_id FROM person_tag")).all()
    assert rows == [("p1", "t1")]


def test_person_tag_composite_pk_dedup(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_person_cascades_into_person_tag(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    # Sanity
    assert session.execute(text("SELECT COUNT(*) FROM person_tag")).scalar() == 1
    session.delete(p)
    session.commit()
    # Cascade: the join row should be gone with the parent
    assert session.execute(text("SELECT COUNT(*) FROM person_tag")).scalar() == 0
    # Tag itself survives — tags are global
    assert session.execute(text("SELECT COUNT(*) FROM tag")).scalar() == 1


def test_deleting_tag_cascades_into_person_tag(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    session.delete(t)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM person_tag")).scalar() == 0
    # Person itself survives
    assert session.execute(text("SELECT COUNT(*) FROM person")).scalar() == 1


def test_person_relationships_navigate_tags(session):
    p = Person(id="p1", alias="Alice")
    t = Tag(id="t1", name="Friend", slug="friend")
    session.add_all([p, t])
    session.commit()
    session.add(PersonTag(person_id="p1", tag_id="t1"))
    session.commit()
    refreshed = session.get(Person, "p1")
    # Person.tags exposes the linked Tag rows via the relationship
    assert [tag.name for tag in refreshed.tags] == ["Friend"]


def test_person_alias_required(session):
    p = Person(id="x", alias=None)  # type: ignore[arg-type]
    session.add(p)
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 4.2: Run failing tests**

```bash
pytest tests/unit/test_db_models.py -v
```

Expected: ImportError on missing `Person`/`Tag`/`PersonTag`.

- [ ] **Step 4.3: Implement `flexlog/db/models.py`**

```python
"""SQLAlchemy ORM models for flexlog.

M2 declares Person, Tag, PersonTag (the people side of the spec's data
model — §7). Sessions, links, media, and avatars come in M3/M4. The
`avatar_media_id` column is declared here as a plain nullable string so
M4 can layer the foreign-key constraint onto media_file without a schema
migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from sqlalchemy import ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flexlog.db import Base


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp string (default for created_at/updated_at)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Person(Base):
    __tablename__ = "person"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    # FK to media_file lands in M4. For now, treat as a free string slot.
    avatar_media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_utcnow_iso, onupdate=_utcnow_iso
    )

    tags: Mapped[List["Tag"]] = relationship(
        secondary="person_tag",
        back_populates="people",
        order_by="Tag.name",
    )


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)

    people: Mapped[List[Person]] = relationship(
        secondary="person_tag",
        back_populates="tags",
    )


class PersonTag(Base):
    __tablename__ = "person_tag"

    person_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("person.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("tag.id", ondelete="CASCADE"),
        primary_key=True,
    )


# Lookup index on slug is already created by the unique constraint above.
# No further indexes in M2; M3 adds session(person_id, session_date).
```

- [ ] **Step 4.4: Run tests, verify pass**

```bash
pytest -v
```

Expected: all 12 new tests pass; gate green.

- [ ] **Step 4.5: Commit**

```bash
git add flexlog/db/models.py tests/unit/test_db_models.py
git commit -m "M2: add Person, Tag, PersonTag models with cascading joins

Cascades on person_tag verified: deleting a person or a tag clears the
join rows; the surviving entity is untouched. avatar_media_id is a free
string column for now; M4 layers the FK to media_file."
```

---

## Task 5: Wire DB engine, secret_key, CSRFProtect into the app factory

The order in `create_app()` becomes:

1. validate `FLEXLOG_DATA_DIR` + ensure layout
2. load or bootstrap `config.json`
3. load or create secret key
4. build the Flask app
5. set `app.config["SECRET_KEY"]` + `WTF_CSRF_ENABLED = True`
6. open the DB engine + run `Base.metadata.create_all()`
7. attach engine + session factory to `app.config`
8. register Jinja filter + context processor (existing)
9. register blueprints (existing — but with M2's blueprints from later tasks)
10. install teardown handler that closes any per-request session

We also expose `flexlog.db.get_db(app)` — fetches a session from `flask.g`, lazily creating one — and `flexlog.db.close_db(error)` — closes it.

**Files:**
- Modify: `flexlog/app.py`
- Modify: `flexlog/db/__init__.py` (add request-scoped helpers)
- Modify: `tests/conftest.py` (CSRF disabled by default for tests; add `db_session` fixture)
- Modify: `tests/integration/test_app_factory.py` (extend with DB + secret_key + CSRF assertions)

- [ ] **Step 5.1: Extend `flexlog/db/__init__.py`**

Append at the end:

```python
from flask import Flask, current_app, g

_SESSION_KEY = "_flexlog_db_session"
_FACTORY_KEY = "FLEXLOG_DB_SESSION_FACTORY"
_ENGINE_KEY = "FLEXLOG_DB_ENGINE"


def attach_to_app(app: Flask, engine: Engine, session_factory: sessionmaker[Session]) -> None:
    """Stash engine + session factory on the Flask app and register teardown."""
    app.config[_ENGINE_KEY] = engine
    app.config[_FACTORY_KEY] = session_factory

    @app.teardown_appcontext
    def _close(_error: BaseException | None) -> None:
        close_db()


def get_db() -> Session:
    """Return the request-scoped Session, creating it on first call.

    Must be called inside a Flask app context (i.e. during a request or
    inside `with app.app_context():`). The session is closed by the
    teardown handler installed in `attach_to_app`.
    """
    if _SESSION_KEY not in g:
        factory = current_app.config[_FACTORY_KEY]
        g.setdefault(_SESSION_KEY, factory())
    return g.get(_SESSION_KEY)


def close_db() -> None:
    """Close + remove the request-scoped Session if one was created."""
    session = g.pop(_SESSION_KEY, None)
    if session is not None:
        session.close()
```

- [ ] **Step 5.2: Update `flexlog/app.py`**

Replace `flexlog/app.py` with the following (full file rewrite — preserving Task 1.B logging refactor):

```python
"""Flask application factory for flexlog."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask
from flask_wtf.csrf import CSRFProtect

from flexlog import paths
from flexlog.config_loader import Config, load_or_bootstrap
from flexlog.db import Base, attach_to_app, make_engine, make_session_factory
from flexlog.secret_key import load_or_create_secret_key
from flexlog.web import register_blueprints
from flexlog.web.filters import build_labels_context, ui_filter

LOGGER_NAME = "flexlog"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def create_app() -> Flask:
    """Build and return the configured Flask app.

    Reads FLEXLOG_DATA_DIR (required), loads/bootstraps config.json, opens
    the SQLite database, and wires CSRF + DB lifecycle. Raises (DataDirError,
    ConfigError, SecretKeyError) on any startup failure. No fallback values
    — startup failures are loud and explicit.
    """
    _configure_logging()

    # 1. Validate data dir + create child layout
    data_dir = paths.data_dir()
    paths.ensure_layout()

    # 2. Load (or bootstrap) config.json
    config: Config = load_or_bootstrap(paths.config_path())

    # 3. Load or create the per-install secret key
    secret_key = load_or_create_secret_key(data_dir / ".secret_key")

    # 4. Build the Flask app
    app = Flask(
        "flexlog",
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["FLEXLOG"] = config
    app.config["FLEXLOG_DATA_DIR"] = str(data_dir)
    app.config["SECRET_KEY"] = secret_key
    app.config["WTF_CSRF_ENABLED"] = True
    app.debug = os.environ.get("FLEXLOG_DEBUG", "") == "1"

    # 5. CSRF
    CSRFProtect(app)

    # 6. Database
    engine = make_engine(paths.db_path())
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    attach_to_app(app, engine, session_factory)

    # 7. Wire up filters + context processor
    app.jinja_env.filters["ui"] = lambda key: ui_filter(key)

    @app.context_processor
    def _inject_labels() -> dict[str, object]:
        return {"labels": build_labels_context(config)}

    # 8. Register blueprints
    register_blueprints(app)

    return app


def _configure_logging() -> None:
    """Attach a stderr handler at INFO to the named flexlog logger.

    Idempotent — only attaches a handler once per process.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
```

- [ ] **Step 5.3: Update `tests/conftest.py`**

Replace the file with:

```python
"""Shared pytest fixtures for flexlog tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flexlog.config_loader import DEFAULT_CONFIG_JSON


@pytest.fixture
def tmp_data_dir_no_config(tmp_path, monkeypatch):
    """An existing, writable data dir with NO config.json yet."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """An existing, writable data dir with the canonical default config.json."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(DEFAULT_CONFIG_JSON, encoding="utf-8")
    return tmp_path


@pytest.fixture
def app(tmp_data_dir):
    """App with CSRF DISABLED — used by the vast majority of tests.

    A separate `csrf_app` fixture is provided for the one CSRF integration
    test that actually needs the protection wired in.
    """
    from flexlog.app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf_app(tmp_data_dir):
    """App with CSRF enabled — for tests that exercise CSRF rejection."""
    from flexlog.app import create_app
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    # WTF_CSRF_ENABLED stays True (the default in production)
    return flask_app


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


@pytest.fixture
def db_session(app):
    """Yield a SQLAlchemy session bound to the test app's engine.

    Operates inside a Flask app context so flexlog.db.get_db() works for
    callers that prefer the production helper.
    """
    from flexlog.db import close_db, get_db

    with app.app_context():
        session = get_db()
        try:
            yield session
        finally:
            close_db()
```

- [ ] **Step 5.4: Extend `tests/integration/test_app_factory.py`**

Append these tests at the END of the existing file:

```python
def test_create_app_writes_secret_key_on_first_run(tmp_data_dir):
    """After create_app() the .secret_key file must exist with mode 0600."""
    import stat

    create_app()
    key_file = tmp_data_dir / ".secret_key"
    assert key_file.exists()
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600


def test_create_app_creates_database_with_tables(tmp_data_dir):
    from sqlalchemy import inspect

    app = create_app()
    engine = app.config["FLEXLOG_DB_ENGINE"]
    names = set(inspect(engine).get_table_names())
    assert {"person", "tag", "person_tag"} <= names


def test_create_app_attaches_session_factory(tmp_data_dir):
    app = create_app()
    factory = app.config["FLEXLOG_DB_SESSION_FACTORY"]
    assert callable(factory)
    with factory() as s:
        from sqlalchemy import text

        assert s.execute(text("SELECT 1")).scalar() == 1


def test_csrf_is_enabled_in_production_default(tmp_data_dir):
    """create_app() must set WTF_CSRF_ENABLED = True by default.

    The `app` fixture overrides this for testing convenience; this test
    constructs the app directly to verify the default.
    """
    app = create_app()
    assert app.config["WTF_CSRF_ENABLED"] is True


def test_get_db_returns_same_session_within_request(app):
    """get_db() must memoize within a single app context."""
    from flexlog.db import close_db, get_db

    with app.app_context():
        a = get_db()
        b = get_db()
        assert a is b
        close_db()
```

- [ ] **Step 5.5: Run tests, verify pass**

```bash
pytest -v
```

Expected: all existing 91 tests + the new ones pass; coverage gate green. The earlier `test_main_uses_loopback_host_and_default_port` and friends still need to mock `Flask.run` — they should still pass because `create_app()` still completes synchronously.

- [ ] **Step 5.6: Commit**

```bash
git add flexlog/app.py flexlog/db/__init__.py \
        tests/conftest.py tests/integration/test_app_factory.py
git commit -m "M2: wire SECRET_KEY, CSRFProtect, and DB engine into app factory

create_app now: loads/creates .secret_key (0600), enables CSRF, opens the
SQLite engine on paths.db_path(), runs Base.metadata.create_all(), and
installs a teardown that closes per-request sessions. Test fixtures
disable CSRF by default; csrf_app/csrf_client fixtures keep it on for
the dedicated CSRF integration test."
```

---

## Task 6: `services/tags.py` — slugify, normalize, get-or-create

Tag identity is the slug. Same display name with different cases collapse to one tag. The slug is the user's display name lowered + non-alphanumerics replaced with `-` + collapsed runs of `-` + stripped of leading/trailing `-`. Empty slugs are rejected.

**Files:**
- Create: `flexlog/services/tags.py`
- Create: `tests/unit/test_tags_service.py`

- [ ] **Step 6.1: Write failing tests**

`tests/unit/test_tags_service.py`:

```python
import pytest

from flexlog.db.models import Tag
from flexlog.services.tags import (
    InvalidTagError,
    get_or_create_tag,
    list_all_tags,
    normalize_tag_input,
    slugify,
)


def test_slugify_basic():
    assert slugify("Engineering") == "engineering"


def test_slugify_collapses_punctuation_and_spaces():
    assert slugify("Senior  Engineer / SRE") == "senior-engineer-sre"


def test_slugify_strips_leading_and_trailing_dashes():
    assert slugify("---hello---") == "hello"


def test_slugify_unicode_is_lowercased():
    """Non-ASCII letters are kept (Chinese, accented) but lowercased."""
    assert slugify("Café") == "café"
    assert slugify("北京 朋友") == "北京-朋友"


def test_slugify_empty_input_raises():
    with pytest.raises(InvalidTagError, match="empty"):
        slugify("   ")


def test_slugify_only_punctuation_raises():
    with pytest.raises(InvalidTagError, match="empty"):
        slugify("---!!!")


def test_normalize_tag_input_splits_and_dedups():
    """Comma-separated user input → list of cleaned (display, slug) pairs."""
    pairs = normalize_tag_input("Engineering, friend , ENGINEERING, , Coach")
    # Order preserved on first appearance; case-insensitive dedup
    assert pairs == [
        ("Engineering", "engineering"),
        ("friend", "friend"),
        ("Coach", "coach"),
    ]


def test_normalize_tag_input_empty_returns_empty_list():
    assert normalize_tag_input("") == []
    assert normalize_tag_input("   ,  ,   ") == []


def test_normalize_tag_input_drops_invalid_silently():
    """Tokens that slugify to empty are dropped; valid tokens still pass."""
    pairs = normalize_tag_input("real, ---, valid")
    assert pairs == [("real", "real"), ("valid", "valid")]


def test_get_or_create_tag_creates_when_missing(db_session):
    tag = get_or_create_tag(db_session, "Engineering")
    db_session.commit()
    assert isinstance(tag, Tag)
    assert tag.name == "Engineering"
    assert tag.slug == "engineering"
    # Round-trip
    got = db_session.query(Tag).filter_by(slug="engineering").one()
    assert got.id == tag.id


def test_get_or_create_tag_reuses_existing(db_session):
    a = get_or_create_tag(db_session, "Engineering")
    db_session.commit()
    b = get_or_create_tag(db_session, "ENGINEERING")
    db_session.commit()
    assert a.id == b.id
    assert a.name == "Engineering"  # First-seen wins on display name


def test_get_or_create_tag_invalid_raises(db_session):
    with pytest.raises(InvalidTagError):
        get_or_create_tag(db_session, "   ")


def test_list_all_tags_orders_by_name(db_session):
    get_or_create_tag(db_session, "Friend")
    get_or_create_tag(db_session, "Coach")
    get_or_create_tag(db_session, "Engineer")
    db_session.commit()
    names = [t.name for t in list_all_tags(db_session)]
    assert names == ["Coach", "Engineer", "Friend"]


def test_list_all_tags_empty(db_session):
    assert list_all_tags(db_session) == []
```

- [ ] **Step 6.2: Run failing tests**

```bash
pytest tests/unit/test_tags_service.py -v
```

Expected: ImportError on missing module.

- [ ] **Step 6.3: Implement `flexlog/services/tags.py`**

```python
"""Tag normalization, slugification, and ORM helpers.

Tags are global per the spec §6.1 and §7. Identity is the slug — different
display capitalizations collapse to a single tag. The slug is computed as:
  1. lowercased
  2. non-alphanumeric (Unicode-aware) → '-'
  3. consecutive '-' collapsed
  4. leading/trailing '-' stripped

Empty slugs are rejected. The display name remains as the user typed it
(first occurrence wins when reusing).
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from flexlog.db.models import Tag

# Unicode-aware non-alphanumeric matcher (\W is [^A-Za-z0-9_]; we use
# `re.UNICODE` flag default and exclude underscore explicitly so e.g.
# 'foo_bar' becomes 'foo-bar'.)
_NON_ALNUM_RE = re.compile(r"[^\w]+", re.UNICODE)
_UNDERSCORE_RE = re.compile(r"_+")
_DASH_RUN_RE = re.compile(r"-{2,}")


class InvalidTagError(ValueError):
    """Raised when a tag name slugifies to an empty string."""


def slugify(name: str) -> str:
    """Compute the canonical slug for a tag name.

    Raises InvalidTagError if the result is empty.
    """
    if not isinstance(name, str):
        raise InvalidTagError(f"tag name must be a string, got {type(name).__name__}")
    lowered = name.lower().strip()
    # Replace runs of non-word chars with a dash, collapse underscores too.
    s = _NON_ALNUM_RE.sub("-", lowered)
    s = _UNDERSCORE_RE.sub("-", s)
    s = _DASH_RUN_RE.sub("-", s)
    s = s.strip("-")
    if not s:
        raise InvalidTagError(f"tag name {name!r} is empty after normalization")
    return s


def normalize_tag_input(raw: str) -> list[tuple[str, str]]:
    """Parse a comma-separated user input into [(display, slug), ...].

    Order: first appearance of each slug. Case-insensitive dedup. Tokens
    whose slug would be empty are dropped silently (so the user can type
    trailing commas without getting an error).
    """
    if not raw:
        return []
    seen_slugs: set[str] = set()
    out: list[tuple[str, str]] = []
    for raw_token in raw.split(","):
        display = raw_token.strip()
        if not display:
            continue
        try:
            sl = slugify(display)
        except InvalidTagError:
            continue
        if sl in seen_slugs:
            continue
        seen_slugs.add(sl)
        out.append((display, sl))
    return out


def get_or_create_tag(session: Session, name: str) -> Tag:
    """Return the Tag whose slug matches `name`, creating one if absent.

    Caller is responsible for `session.commit()`. Raises InvalidTagError
    if `name` slugifies to empty.
    """
    sl = slugify(name)
    existing = session.execute(select(Tag).where(Tag.slug == sl)).scalar_one_or_none()
    if existing is not None:
        return existing
    new_tag = Tag(id=str(uuid.uuid4()), name=name.strip(), slug=sl)
    session.add(new_tag)
    session.flush()  # so .id is queryable before commit
    return new_tag


def list_all_tags(session: Session) -> list[Tag]:
    """Return all tags in alphabetical-by-name order."""
    return list(session.execute(select(Tag).order_by(Tag.name)).scalars())
```

- [ ] **Step 6.4: Run tests, verify pass**

```bash
pytest -v
```

Expected: all tag service tests pass.

- [ ] **Step 6.5: Commit**

```bash
git add flexlog/services/tags.py tests/unit/test_tags_service.py
git commit -m "M2: add tag service — slugify, normalize, get-or-create

slugify() is Unicode-aware (preserves CJK, lowercases, collapses
non-alnum to dashes). normalize_tag_input() parses the user's
comma-separated form into deduped (display, slug) pairs. get_or_create
hits a unique-slug index for idempotent reuse."
```

---

## Task 7: `services/people.py` — Person CRUD + search

**Files:**
- Create: `flexlog/services/people.py`
- Create: `tests/unit/test_people_service.py`

- [ ] **Step 7.1: Write failing tests**

`tests/unit/test_people_service.py`:

```python
import pytest

from flexlog.db.models import Person, Tag
from flexlog.services.people import (
    PersonNotFoundError,
    create_person,
    delete_person,
    get_person,
    list_people,
    search_people,
    update_person,
)


def test_create_person_minimal(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    assert p.id  # UUID assigned
    assert p.alias == "Alice"
    assert p.tags == []


def test_create_person_with_tags(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Engineer, Friend")
    db_session.commit()
    assert sorted(t.name for t in p.tags) == ["Engineer", "Friend"]


def test_create_person_dedup_tags_via_slug(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Engineer, ENGINEER")
    db_session.commit()
    assert len(p.tags) == 1
    assert p.tags[0].slug == "engineer"


def test_create_person_alias_required(db_session):
    with pytest.raises(ValueError, match="alias"):
        create_person(db_session, alias="", tag_input="")
    with pytest.raises(ValueError, match="alias"):
        create_person(db_session, alias="   ", tag_input="")


def test_get_person_returns_none_when_missing(db_session):
    assert get_person(db_session, "nope") is None


def test_get_person_returns_match(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    got = get_person(db_session, p.id)
    assert got is not None
    assert got.id == p.id


def test_list_people_empty(db_session):
    assert list_people(db_session) == []


def test_list_people_alphabetical_by_alias(db_session):
    create_person(db_session, alias="Charlie", tag_input="")
    create_person(db_session, alias="Alice", tag_input="")
    create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    names = [p.alias for p in list_people(db_session)]
    assert names == ["Alice", "Bob", "Charlie"]


def test_search_people_by_alias_substring(db_session):
    create_person(db_session, alias="Alice Smith", tag_input="")
    create_person(db_session, alias="Bob Jones", tag_input="")
    db_session.commit()
    results = search_people(db_session, "alice")
    assert [p.alias for p in results] == ["Alice Smith"]


def test_search_people_by_tag_name(db_session):
    create_person(db_session, alias="Alice", tag_input="Engineer")
    create_person(db_session, alias="Bob", tag_input="Coach")
    db_session.commit()
    results = search_people(db_session, "engineer")
    assert [p.alias for p in results] == ["Alice"]


def test_search_people_by_tag_slug(db_session):
    create_person(db_session, alias="Alice", tag_input="Senior Engineer")
    db_session.commit()
    results = search_people(db_session, "senior-engineer")
    assert [p.alias for p in results] == ["Alice"]


def test_search_people_case_insensitive(db_session):
    create_person(db_session, alias="Alice", tag_input="Engineer")
    db_session.commit()
    assert len(search_people(db_session, "ALICE")) == 1
    assert len(search_people(db_session, "ENGINEER")) == 1


def test_search_people_empty_query_returns_all(db_session):
    create_person(db_session, alias="Alice", tag_input="")
    create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    assert len(search_people(db_session, "")) == 2
    assert len(search_people(db_session, "   ")) == 2


def test_search_people_no_match(db_session):
    create_person(db_session, alias="Alice", tag_input="Engineer")
    db_session.commit()
    assert search_people(db_session, "zebra") == []


def test_search_people_dedups_when_alias_and_tag_both_match(db_session):
    """A person whose alias contains the query AND who has a matching tag must
    appear once, not twice."""
    create_person(db_session, alias="Engineer Bob", tag_input="Engineer")
    db_session.commit()
    results = search_people(db_session, "engineer")
    assert len(results) == 1


def test_update_person_alias_and_tags(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    update_person(db_session, p.id, alias="Alicia", tag_input="Coach, Mentor")
    db_session.commit()
    refreshed = get_person(db_session, p.id)
    assert refreshed.alias == "Alicia"
    assert sorted(t.name for t in refreshed.tags) == ["Coach", "Mentor"]


def test_update_person_clearing_tags(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    update_person(db_session, p.id, alias="Alice", tag_input="")
    db_session.commit()
    assert get_person(db_session, p.id).tags == []


def test_update_person_alias_required(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    with pytest.raises(ValueError, match="alias"):
        update_person(db_session, p.id, alias="  ", tag_input="")


def test_update_person_missing_raises(db_session):
    with pytest.raises(PersonNotFoundError):
        update_person(db_session, "nope", alias="X", tag_input="")


def test_delete_person_removes_row(db_session):
    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    delete_person(db_session, p.id)
    db_session.commit()
    assert get_person(db_session, p.id) is None


def test_delete_person_does_not_orphan_tag(db_session):
    """Tags are global — deleting a person must not delete their tags."""
    from flexlog.services.tags import list_all_tags

    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    delete_person(db_session, p.id)
    db_session.commit()
    assert [t.name for t in list_all_tags(db_session)] == ["Friend"]


def test_delete_person_missing_raises(db_session):
    with pytest.raises(PersonNotFoundError):
        delete_person(db_session, "nope")
```

- [ ] **Step 7.2: Run failing tests**

```bash
pytest tests/unit/test_people_service.py -v
```

Expected: ImportError on missing module.

- [ ] **Step 7.3: Implement `flexlog/services/people.py`**

```python
"""Person CRUD + dashboard search.

Tags travel with the person via `services.tags.normalize_tag_input` and
`services.tags.get_or_create_tag` so the route layer never touches Tag
directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from flexlog.db.models import Person, PersonTag, Tag
from flexlog.services.tags import (
    get_or_create_tag,
    normalize_tag_input,
)


class PersonNotFoundError(LookupError):
    """Raised by update/delete when the target person id does not exist."""


def _validate_alias(alias: str) -> str:
    if not isinstance(alias, str) or alias.strip() == "":
        raise ValueError("alias is required and must not be empty or whitespace-only")
    return alias.strip()


def _apply_tags(session: Session, person: Person, tag_input: str) -> None:
    """Replace person.tags to match the parsed tag_input.

    Existing PersonTag rows for tags no longer present are removed; new ones
    are created. Tags themselves are never deleted.
    """
    desired_pairs = normalize_tag_input(tag_input)
    desired_slugs = {sl for _name, sl in desired_pairs}
    # Drop joins for tags no longer desired
    person.tags = [t for t in person.tags if t.slug in desired_slugs]
    # Add joins for new tags (use get_or_create_tag to keep dedup)
    existing_slugs = {t.slug for t in person.tags}
    for display, sl in desired_pairs:
        if sl in existing_slugs:
            continue
        tag = get_or_create_tag(session, display)
        person.tags.append(tag)


def create_person(session: Session, alias: str, tag_input: str) -> Person:
    """Create a Person with the given alias and comma-separated tag input.

    Caller is responsible for committing. Raises ValueError if alias is empty.
    """
    person = Person(id=str(uuid.uuid4()), alias=_validate_alias(alias))
    session.add(person)
    session.flush()
    _apply_tags(session, person, tag_input)
    return person


def get_person(session: Session, person_id: str) -> Person | None:
    """Return the Person with this id, or None if absent. Eager-loads tags."""
    stmt = select(Person).where(Person.id == person_id).options(selectinload(Person.tags))
    return session.execute(stmt).scalar_one_or_none()


def list_people(session: Session) -> list[Person]:
    """All people, alphabetical by alias (case-insensitive)."""
    stmt = (
        select(Person)
        .order_by(Person.alias.collate("NOCASE"))
        .options(selectinload(Person.tags))
    )
    return list(session.execute(stmt).scalars())


def search_people(session: Session, query: str) -> list[Person]:
    """Search people whose alias contains `query` OR who carry a tag whose
    name or slug contains `query`. Case-insensitive. Empty query → all.
    """
    q = (query or "").strip()
    if q == "":
        return list_people(session)
    like = f"%{q.lower()}%"
    stmt = (
        select(Person)
        .outerjoin(PersonTag, PersonTag.person_id == Person.id)
        .outerjoin(Tag, Tag.id == PersonTag.tag_id)
        .where(
            or_(
                Person.alias.ilike(like),
                Tag.name.ilike(like),
                Tag.slug.ilike(like),
            )
        )
        .order_by(Person.alias.collate("NOCASE"))
        .distinct()
        .options(selectinload(Person.tags))
    )
    return list(session.execute(stmt).scalars().unique())


def update_person(
    session: Session, person_id: str, alias: str, tag_input: str
) -> Person:
    """Update an existing person's alias and tags. Raises PersonNotFoundError."""
    person = get_person(session, person_id)
    if person is None:
        raise PersonNotFoundError(person_id)
    person.alias = _validate_alias(alias)
    _apply_tags(session, person, tag_input)
    return person


def delete_person(session: Session, person_id: str) -> None:
    """Delete a person. Cascades through person_tag (FK) but leaves tags."""
    person = get_person(session, person_id)
    if person is None:
        raise PersonNotFoundError(person_id)
    session.delete(person)
```

- [ ] **Step 7.4: Run tests, verify pass**

```bash
pytest -v
```

- [ ] **Step 7.5: Commit**

```bash
git add flexlog/services/people.py tests/unit/test_people_service.py
git commit -m "M2: add Person service — CRUD + search across alias/tag/slug

create/update use normalize_tag_input → get_or_create_tag for tags so
duplicate slugs collapse. search_people unions alias-substring and
tag-name/slug-substring with .distinct(). Tags survive person deletion."
```

---

## Task 8: `web/forms.py` — `PersonForm`

**Files:**
- Create: `flexlog/web/forms.py`
- Create: `tests/unit/test_forms.py`

- [ ] **Step 8.1: Write failing tests**

`tests/unit/test_forms.py`:

```python
import pytest

from flexlog.web.forms import PersonForm


def test_person_form_alias_required(app):
    with app.test_request_context(method="POST", data={"alias": "", "tags": ""}):
        form = PersonForm()
        assert not form.validate()
        assert "alias" in form.errors


def test_person_form_alias_whitespace_rejected(app):
    with app.test_request_context(method="POST", data={"alias": "   ", "tags": ""}):
        form = PersonForm()
        assert not form.validate()
        assert "alias" in form.errors


def test_person_form_valid_with_alias_only(app):
    with app.test_request_context(method="POST", data={"alias": "Alice", "tags": ""}):
        form = PersonForm()
        assert form.validate(), form.errors


def test_person_form_alias_max_length(app):
    """Reject absurdly long aliases that would break UI layout."""
    long = "x" * 201
    with app.test_request_context(method="POST", data={"alias": long, "tags": ""}):
        form = PersonForm()
        assert not form.validate()
        assert "alias" in form.errors


def test_person_form_tags_max_length(app):
    """Reject absurdly long tag inputs."""
    long = "x" * 1001
    with app.test_request_context(method="POST", data={"alias": "Alice", "tags": long}):
        form = PersonForm()
        assert not form.validate()
        assert "tags" in form.errors
```

- [ ] **Step 8.2: Run failing tests**

```bash
pytest tests/unit/test_forms.py -v
```

Expected: ImportError on missing module.

- [ ] **Step 8.3: Implement `flexlog/web/forms.py`**

```python
"""Flask-WTF forms.

Forms are intentionally thin — validation logic lives in services. The
form's job is to enforce presence and length so we don't pass garbage into
the service layer or hold absurd strings in memory.
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Optional

ALIAS_MAX = 200
TAGS_MAX = 1000  # comma-separated free text


class PersonForm(FlaskForm):
    alias = StringField(
        "alias",
        validators=[DataRequired(message="alias is required"), Length(max=ALIAS_MAX)],
    )
    tags = StringField(
        "tags",
        validators=[Optional(), Length(max=TAGS_MAX)],
    )
```

- [ ] **Step 8.4: Run tests**

```bash
pytest -v
```

- [ ] **Step 8.5: Commit**

```bash
git add flexlog/web/forms.py tests/unit/test_forms.py
git commit -m "M2: add PersonForm — alias required, tags optional, length caps

Validation guards: alias presence (no whitespace), alias ≤ 200 chars,
tags free-text ≤ 1000 chars."
```

---

## Task 9: `web/people_bp.py` — new/create + edit/update routes

**Files:**
- Create: `flexlog/web/people_bp.py`
- Create: `flexlog/templates/people/new.html`
- Create: `flexlog/templates/people/edit.html`
- Create: `flexlog/templates/_partials/avatar_placeholder.html`
- Create: `flexlog/templates/_partials/tag_chip.html`
- Modify: `flexlog/web/__init__.py` (register the blueprint — keep `home_bp` for now; Task 11 swaps it out)
- Modify: `flexlog/web/filters.py` (extend BUILTIN_UI_DEFAULTS)
- Create: `tests/integration/test_people_routes.py`

- [ ] **Step 9.1: Extend BUILTIN_UI_DEFAULTS**

In `flexlog/web/filters.py`, replace the `BUILTIN_UI_DEFAULTS` dict with:

```python
BUILTIN_UI_DEFAULTS: dict[str, str] = {
    # M1
    "new_person": "New Person",
    "empty_dashboard": "Nothing here yet.",
    "search_placeholder": "Search",
    "add_session": "Add Session",
    # M2
    "edit_person": "Edit",
    "delete_person": "Delete",
    "delete_person_confirm_prompt": "Type the alias to confirm deletion:",
    "save": "Save",
    "cancel": "Cancel",
    "tags_label": "Tags",
    "alias_label": "Alias",
    "tags_help": "Comma-separated. Same tag with different capitalization counts once.",
    "untagged": "Untagged",
    "no_sessions_yet": "No sessions yet.",
}
```

- [ ] **Step 9.2: Write the failing integration tests**

`tests/integration/test_people_routes.py`:

```python
def _post(client, url, data):
    return client.post(url, data=data, follow_redirects=False)


def test_get_new_person_form_renders(client):
    resp = client.get("/people/new")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Alias" in body
    assert "Tags" in body
    # Comes from BUILTIN_UI_DEFAULTS
    assert "Save" in body


def test_post_create_person_minimal(client):
    resp = _post(client, "/people", {"alias": "Alice", "tags": ""})
    assert resp.status_code == 302  # redirect to detail page
    assert "/people/" in resp.headers["Location"]


def test_post_create_person_with_tags(client, db_session):
    from flexlog.db.models import Person

    _post(client, "/people", {"alias": "Alice", "tags": "Engineer, Friend"})
    p = db_session.query(Person).filter_by(alias="Alice").one()
    assert sorted(t.name for t in p.tags) == ["Engineer", "Friend"]


def test_post_create_person_empty_alias_rerenders_form(client):
    resp = client.post("/people", data={"alias": "", "tags": ""})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "alias" in body.lower()


def test_get_edit_person_form_prefills(client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="Engineer, Friend")
    db_session.commit()
    resp = client.get(f"/people/{p.id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Alice" in body
    # Tag input should pre-populate with display names
    assert "Engineer" in body
    assert "Friend" in body


def test_get_edit_person_404_when_missing(client):
    resp = client.get("/people/no-such-id/edit")
    assert resp.status_code == 404


def test_post_update_person(client, db_session):
    from flexlog.services.people import create_person, get_person

    p = create_person(db_session, alias="Alice", tag_input="Friend")
    db_session.commit()
    resp = _post(client, f"/people/{p.id}", {"alias": "Alicia", "tags": "Coach"})
    assert resp.status_code == 302
    refreshed = get_person(db_session, p.id)
    db_session.refresh(refreshed)
    assert refreshed.alias == "Alicia"
    assert [t.name for t in refreshed.tags] == ["Coach"]


def test_post_update_person_404_when_missing(client):
    resp = client.post("/people/no-such-id", data={"alias": "X", "tags": ""})
    assert resp.status_code == 404


def test_post_update_person_empty_alias_rerenders_form(client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    resp = client.post(f"/people/{p.id}", data={"alias": "", "tags": ""})
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "alias" in body.lower()


def test_xss_in_alias_is_escaped(client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="<script>alert(1)</script>", tag_input="")
    db_session.commit()
    resp = client.get(f"/people/{p.id}/edit")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_xss_in_tag_name_is_escaped(client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="<img onerror=x>")
    db_session.commit()
    resp = client.get(f"/people/{p.id}/edit")
    body = resp.get_data(as_text=True)
    assert "<img onerror=x>" not in body
```

- [ ] **Step 9.3: Implement `flexlog/web/people_bp.py`**

```python
"""People CRUD routes."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from flexlog.db import get_db
from flexlog.services.people import (
    PersonNotFoundError,
    create_person,
    delete_person,
    get_person,
    update_person,
)
from flexlog.web.forms import PersonForm

people_bp = Blueprint("people", __name__, url_prefix="/people")


def _person_or_404(person_id: str):
    person = get_person(get_db(), person_id)
    if person is None:
        abort(404)
    return person


def _tag_input_from_person(person) -> str:
    return ", ".join(t.name for t in person.tags)


@people_bp.get("/new")
def new():
    form = PersonForm()
    return render_template("people/new.html", form=form)


@people_bp.post("")
def create():
    form = PersonForm()
    if not form.validate_on_submit():
        return render_template("people/new.html", form=form), 400
    db = get_db()
    person = create_person(
        db,
        alias=form.alias.data,
        tag_input=form.tags.data or "",
    )
    db.commit()
    return redirect(url_for("people.detail", person_id=person.id))


@people_bp.get("/<person_id>/edit")
def edit(person_id: str):
    person = _person_or_404(person_id)
    form = PersonForm(data={"alias": person.alias, "tags": _tag_input_from_person(person)})
    return render_template("people/edit.html", form=form, person=person)


@people_bp.post("/<person_id>")
def update(person_id: str):
    person = _person_or_404(person_id)
    form = PersonForm()
    if not form.validate_on_submit():
        return render_template("people/edit.html", form=form, person=person), 400
    db = get_db()
    try:
        update_person(
            db, person_id,
            alias=form.alias.data,
            tag_input=form.tags.data or "",
        )
    except PersonNotFoundError:
        abort(404)
    db.commit()
    return redirect(url_for("people.detail", person_id=person_id))


# Detail + delete routes are added in Task 10.
```

- [ ] **Step 9.4: Update `flexlog/web/__init__.py`**

```python
"""flexlog blueprints + Flask wiring helpers."""

from __future__ import annotations

from flask import Flask

from flexlog.web.home_bp import home_bp
from flexlog.web.people_bp import people_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(home_bp)
    app.register_blueprint(people_bp)
```

- [ ] **Step 9.5: Add the avatar placeholder partial**

`flexlog/templates/_partials/avatar_placeholder.html`:

```jinja
{# Renders a simple circular initial avatar. Used everywhere until M5. #}
{% set _ = person if person is defined else None %}
<span class="avatar-placeholder" aria-hidden="true">
  {{ (person.alias[0] if person and person.alias else "?") | upper }}
</span>
```

- [ ] **Step 9.6: Add the tag chip partial**

`flexlog/templates/_partials/tag_chip.html`:

```jinja
{# Renders a single tag chip. Caller passes `tag` (Tag ORM object). #}
<span class="tag-chip">{{ tag.name }}</span>
```

- [ ] **Step 9.7: Add `flexlog/templates/people/new.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ "new_person" | ui }} — {{ labels.app_name }}{% endblock %}

{% block content %}
<section class="form-section">
  <h2>{{ "new_person" | ui }}</h2>
  <form method="post" action="{{ url_for('people.create') }}" class="person-form">
    {{ form.csrf_token }}
    <div class="form-row">
      <label for="alias">{{ "alias_label" | ui }}</label>
      {{ form.alias(id="alias", autofocus=True, autocomplete="off") }}
      {% for err in form.alias.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
    </div>
    <div class="form-row">
      <label for="tags">{{ "tags_label" | ui }}</label>
      {{ form.tags(id="tags", autocomplete="off") }}
      <p class="form-help">{{ "tags_help" | ui }}</p>
      {% for err in form.tags.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
    </div>
    <div class="form-actions">
      <button type="submit" class="btn btn-primary">{{ "save" | ui }}</button>
      <a class="btn btn-link" href="{{ url_for('home.home') }}">{{ "cancel" | ui }}</a>
    </div>
  </form>
</section>
{% endblock %}
```

- [ ] **Step 9.8: Add `flexlog/templates/people/edit.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ "edit_person" | ui }}: {{ person.alias }} — {{ labels.app_name }}{% endblock %}

{% block content %}
<section class="form-section">
  <h2>{{ "edit_person" | ui }}: {{ person.alias }}</h2>
  <form method="post" action="{{ url_for('people.update', person_id=person.id) }}" class="person-form">
    {{ form.csrf_token }}
    <div class="form-row">
      <label for="alias">{{ "alias_label" | ui }}</label>
      {{ form.alias(id="alias", autocomplete="off") }}
      {% for err in form.alias.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
    </div>
    <div class="form-row">
      <label for="tags">{{ "tags_label" | ui }}</label>
      {{ form.tags(id="tags", autocomplete="off") }}
      <p class="form-help">{{ "tags_help" | ui }}</p>
      {% for err in form.tags.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
    </div>
    <div class="form-actions">
      <button type="submit" class="btn btn-primary">{{ "save" | ui }}</button>
      <a class="btn btn-link" href="{{ url_for('people.detail', person_id=person.id) }}">{{ "cancel" | ui }}</a>
    </div>
  </form>
</section>
{% endblock %}
```

(Note: the edit template references `people.detail` which is added in Task 10. That's fine — `url_for` resolves at render time, and Task 9's tests don't follow the edit-cancel link.)

- [ ] **Step 9.9: Run tests, verify pass**

```bash
pytest -v
```

Expected: all unit + integration tests pass. The new `people_bp` integration tests rely on `dashboard_bp` not yet existing, so the `/people/new` and `/people` routes work; `home.home` is still the M1 placeholder at `/`.

If any test fails because the `home.html` template's "New Person" button still points to `#`, that's fine — the test doesn't click it.

- [ ] **Step 9.10: Commit**

```bash
git add flexlog/web/people_bp.py flexlog/web/__init__.py flexlog/web/filters.py \
        flexlog/templates/people/new.html flexlog/templates/people/edit.html \
        flexlog/templates/_partials/avatar_placeholder.html \
        flexlog/templates/_partials/tag_chip.html \
        tests/integration/test_people_routes.py
git commit -m "M2: add Person new/create/edit/update routes + templates

Detail + delete come in Task 10. Avatar placeholder partial uses initials
(no avatar upload until M5). Tag input is a single comma-separated field
with a help line; the chip-preview JS is added with the dashboard."
```

---

## Task 10: Person detail + delete (type-alias confirmation)

**Files:**
- Modify: `flexlog/web/people_bp.py` (add detail + delete handlers)
- Create: `flexlog/templates/people/detail.html`
- Create: `tests/integration/test_people_delete.py`
- Modify: `tests/integration/test_people_routes.py` (add detail tests)

- [ ] **Step 10.1: Append failing detail tests to `tests/integration/test_people_routes.py`**

Append at the end:

```python
def test_get_person_detail(client, db_session):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias="Alice", tag_input="Friend, Engineer")
    db_session.commit()
    resp = client.get(f"/people/{p.id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Alias is rendered
    assert "Alice" in body
    # Tag chips render
    assert "Friend" in body
    assert "Engineer" in body
    # Empty session list copy from BUILTIN_UI_DEFAULTS
    assert "No sessions yet" in body
    # Edit link present
    assert f"/people/{p.id}/edit" in body
    # Delete link/form present
    assert f"/people/{p.id}/delete" in body


def test_get_person_detail_404(client):
    resp = client.get("/people/no-such-id")
    assert resp.status_code == 404
```

- [ ] **Step 10.2: Write `tests/integration/test_people_delete.py`**

```python
def _create_person(db_session, alias="Alice", tags=""):
    from flexlog.services.people import create_person

    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def test_delete_person_with_correct_alias_succeeds(client, db_session):
    from flexlog.services.people import get_person

    p = _create_person(db_session, alias="Alice")
    resp = client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": "Alice"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    assert get_person(db_session, p.id) is None


def test_delete_person_with_wrong_alias_rerenders_with_error(client, db_session):
    from flexlog.services.people import get_person

    p = _create_person(db_session, alias="Alice")
    resp = client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": "Bob"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "alias" in body.lower()
    # Person must still exist
    assert get_person(db_session, p.id) is not None


def test_delete_person_with_empty_alias_rerenders_with_error(client, db_session):
    p = _create_person(db_session, alias="Alice")
    resp = client.post(
        f"/people/{p.id}/delete",
        data={"confirm_alias": ""},
    )
    assert resp.status_code == 400


def test_delete_person_404_when_missing(client):
    resp = client.post("/people/no-such-id/delete", data={"confirm_alias": "X"})
    assert resp.status_code == 404


def test_delete_person_alias_check_is_case_sensitive(client, db_session):
    """The user must type the alias exactly. Case mismatch is not a confirmation."""
    p = _create_person(db_session, alias="Alice")
    resp = client.post(f"/people/{p.id}/delete", data={"confirm_alias": "alice"})
    assert resp.status_code == 400
```

- [ ] **Step 10.3: Append to `flexlog/web/people_bp.py`**

Add (alongside the existing handlers):

```python
@people_bp.get("/<person_id>")
def detail(person_id: str):
    person = _person_or_404(person_id)
    return render_template("people/detail.html", person=person)


@people_bp.post("/<person_id>/delete")
def destroy(person_id: str):
    person = _person_or_404(person_id)
    confirm = (request.form.get("confirm_alias") or "").strip()
    if confirm != person.alias:
        flash("Alias did not match — person not deleted.", "error")
        return render_template("people/detail.html", person=person, delete_error=True), 400
    db = get_db()
    try:
        delete_person(db, person_id)
    except PersonNotFoundError:
        abort(404)
    db.commit()
    flash(f"Deleted {person.alias}.", "success")
    return redirect(url_for("home.home"))
```

- [ ] **Step 10.4: Write `flexlog/templates/people/detail.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ person.alias }} — {{ labels.app_name }}{% endblock %}

{% block content %}
<section class="person-detail">
  <header class="person-detail-header">
    {% include "_partials/avatar_placeholder.html" %}
    <div class="person-detail-meta">
      <h2>{{ person.alias }}</h2>
      {% if person.tags %}
      <ul class="tag-chip-list">
        {% for tag in person.tags %}
          <li>{% include "_partials/tag_chip.html" %}</li>
        {% endfor %}
      </ul>
      {% endif %}
    </div>
    <div class="person-detail-actions">
      <a class="btn" href="{{ url_for('people.edit', person_id=person.id) }}">{{ "edit_person" | ui }}</a>
      <a class="btn btn-disabled" href="#" aria-disabled="true" title="Coming in M3">{{ "add_session" | ui }}</a>
    </div>
  </header>

  <section class="sessions-section">
    <h3>{{ labels.session.plural }}</h3>
    <p class="empty-state">{{ "no_sessions_yet" | ui }}</p>
  </section>

  <section class="danger-zone">
    <h3>{{ "delete_person" | ui }}</h3>
    <p>{{ "delete_person_confirm_prompt" | ui }} <strong>{{ person.alias }}</strong></p>
    <form method="post" action="{{ url_for('people.destroy', person_id=person.id) }}" class="delete-form">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <input type="text" name="confirm_alias" autocomplete="off" placeholder="{{ person.alias }}">
      <button type="submit" class="btn btn-danger">{{ "delete_person" | ui }}</button>
    </form>
    {% if delete_error %}
      <p class="form-error">Alias did not match.</p>
    {% endif %}
  </section>
</section>
{% endblock %}
```

- [ ] **Step 10.5: Run tests, verify pass**

```bash
pytest -v
```

- [ ] **Step 10.6: Commit**

```bash
git add flexlog/web/people_bp.py flexlog/templates/people/detail.html \
        tests/integration/test_people_routes.py tests/integration/test_people_delete.py
git commit -m "M2: add Person detail page + type-alias delete confirmation

Detail shows alias, tag chips, edit/add-session buttons (add-session
disabled until M3), and the empty session list. Delete requires the
user to type the exact alias (case-sensitive) before the row is removed."
```

---

## Task 11: Replace home_bp with dashboard_bp (people list + search)

**Files:**
- Create: `flexlog/web/dashboard_bp.py`
- Delete: `flexlog/web/home_bp.py`
- Modify: `flexlog/web/__init__.py`
- Create: `flexlog/templates/dashboard.html`
- Create: `flexlog/templates/_partials/person_card.html`
- Delete: `flexlog/templates/home.html`
- Modify: `tests/integration/test_home_route.py` → `tests/integration/test_dashboard.py` (rename + extend)

- [ ] **Step 11.1: Write the failing dashboard tests**

`tests/integration/test_dashboard.py`:

```python
def _create(db_session, alias, tags=""):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def test_dashboard_empty_state(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Interview Log" in body  # app name still rendered
    assert "Guests" in body  # entity plural
    # Empty state copy from config
    assert "No guests yet. Add your first guest to begin." in body
    # New-person button is now wired to /people/new (no longer #)
    assert "/people/new" in body


def test_dashboard_lists_people(client, db_session):
    _create(db_session, "Alice", "Engineer")
    _create(db_session, "Bob", "Coach")
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "Alice" in body
    assert "Bob" in body
    # Tag chips render
    assert "Engineer" in body
    assert "Coach" in body
    # Person cards link to detail pages
    from flexlog.db.models import Person
    alice = db_session.query(Person).filter_by(alias="Alice").one()
    assert f"/people/{alice.id}" in body


def test_dashboard_search_by_alias(client, db_session):
    _create(db_session, "Alice")
    _create(db_session, "Bob")
    resp = client.get("/?q=alice")
    body = resp.get_data(as_text=True)
    assert "Alice" in body
    assert "Bob" not in body


def test_dashboard_search_by_tag(client, db_session):
    _create(db_session, "Alice", "Engineer")
    _create(db_session, "Bob", "Coach")
    resp = client.get("/?q=coach")
    body = resp.get_data(as_text=True)
    assert "Bob" in body
    assert "Alice" not in body


def test_dashboard_search_no_match(client, db_session):
    _create(db_session, "Alice", "Engineer")
    resp = client.get("/?q=zebra")
    body = resp.get_data(as_text=True)
    assert "Alice" not in body
    # Search-empty state shown
    assert "No guests yet" in body or "no matches" in body.lower() or "0 results" in body.lower()


def test_dashboard_xss_safe_alias(client, db_session):
    _create(db_session, "<script>alert(1)</script>", "")
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_dashboard_search_query_echoed_safely(client):
    """The search query is echoed back into the input field; ensure XSS-safe."""
    resp = client.get("/?q=<img+onerror=x>")
    body = resp.get_data(as_text=True)
    assert "<img onerror=x>" not in body
```

- [ ] **Step 11.2: Delete the old `home_bp.py` and `home.html`**

```bash
git rm flexlog/web/home_bp.py flexlog/templates/home.html
```

(They'll be replaced by the dashboard equivalents below. Some test files reference `home.home` or `home.html` — those should be migrated to `dashboard.home` in this task.)

- [ ] **Step 11.3: Move and rename the existing `test_home_route.py`**

```bash
git mv tests/integration/test_home_route.py tests/integration/test_dashboard_legacy.py
```

Then **delete** the file content (`> tests/integration/test_dashboard_legacy.py` or use the editor to empty it) — its assertions are now subsumed by `test_dashboard.py`. Then delete the empty file:

```bash
git rm tests/integration/test_dashboard_legacy.py
```

- [ ] **Step 11.4: Implement `flexlog/web/dashboard_bp.py`**

```python
"""Dashboard route (root /).

Replaces the M1 placeholder home_bp. The endpoint name remains `home.home`
so existing url_for() calls in templates and redirects from
/people/<id>/delete continue to work — wait, actually we rename it. The
renames:

  - blueprint name: dashboard_bp (the Python variable)
  - blueprint endpoint name: 'home' (preserved so url_for('home.home') keeps working)
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from flexlog.db import get_db
from flexlog.services.people import search_people

# Endpoint name MUST stay "home" to preserve url_for("home.home") calls
# in M1's existing templates.
dashboard_bp = Blueprint("home", __name__)


@dashboard_bp.get("/")
def home():
    query = request.args.get("q", "").strip()
    people = search_people(get_db(), query)
    return render_template("dashboard.html", people=people, query=query)
```

- [ ] **Step 11.5: Update `flexlog/web/__init__.py`**

```python
"""flexlog blueprints + Flask wiring helpers."""

from __future__ import annotations

from flask import Flask

from flexlog.web.dashboard_bp import dashboard_bp
from flexlog.web.people_bp import people_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(people_bp)
```

- [ ] **Step 11.6: Add `flexlog/templates/_partials/person_card.html`**

```jinja
{# Renders a single person card. Caller passes `person`. #}
<a class="person-card" href="{{ url_for('people.detail', person_id=person.id) }}">
  {% include "_partials/avatar_placeholder.html" %}
  <div class="person-card-meta">
    <span class="person-card-alias">{{ person.alias }}</span>
    {% if person.tags %}
    <ul class="tag-chip-list">
      {% for tag in person.tags %}
      <li>{% include "_partials/tag_chip.html" %}</li>
      {% endfor %}
    </ul>
    {% endif %}
  </div>
</a>
```

- [ ] **Step 11.7: Add `flexlog/templates/dashboard.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ labels.entity.plural }} — {{ labels.app_name }}{% endblock %}

{% block content %}
<section class="dashboard">
  <header class="dashboard-header">
    <h2>{{ labels.entity.plural }}</h2>
    <a class="btn btn-primary" href="{{ url_for('people.new') }}">{{ "new_person" | ui }}</a>
  </header>

  <form method="get" action="{{ url_for('home.home') }}" class="dashboard-search">
    <label for="q" class="visually-hidden">{{ "search_placeholder" | ui }}</label>
    <input id="q" type="search" name="q" value="{{ query }}" placeholder="{{ "search_placeholder" | ui }}" autocomplete="off">
  </form>

  {% if people %}
    <ul class="person-grid">
      {% for person in people %}
        <li>{% include "_partials/person_card.html" %}</li>
      {% endfor %}
    </ul>
  {% elif query %}
    <p class="empty-state">No matches for &ldquo;{{ query }}&rdquo;.</p>
  {% else %}
    <p class="empty-state">{{ "empty_dashboard" | ui }}</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 11.8: Run tests, verify pass**

```bash
pytest -v
```

The dashboard tests should now all pass. The earlier `test_home_xss_safe_app_name` and `test_home_uses_builtin_default_when_user_omits_key` tests have been deleted with `home_bp.py`/`home.html` and replaced by equivalent tests in `test_dashboard.py` (`test_dashboard_xss_safe_alias`).

Note: `test_create_app_csp_friendly_no_debug_by_default` and other M1 app-factory tests that don't reference home routing should still pass.

- [ ] **Step 11.9: Commit**

```bash
git add flexlog/web/dashboard_bp.py flexlog/web/__init__.py \
        flexlog/templates/dashboard.html flexlog/templates/_partials/person_card.html \
        tests/integration/test_dashboard.py
git commit -m "M2: replace home_bp with dashboard listing people + search

Endpoint name 'home.home' is preserved so existing url_for() callers
keep working. Dashboard renders person cards from search_people; an
empty query returns all people; an unmatched query renders a no-matches
empty state."
```

---

## Task 12: CSS additions + tag-chip preview JS

**Files:**
- Modify: `flexlog/static/css/main.css` (append rules)
- Create: `flexlog/static/js/people_form.js`
- Modify: `flexlog/templates/people/new.html` and `edit.html` (load the JS)

- [ ] **Step 12.1: Append to `flexlog/static/css/main.css`**

Append at the end:

```css
/* M2 — people grid + cards */

.dashboard-search {
  margin-bottom: 1rem;
}
.dashboard-search input[type="search"] {
  width: 100%;
  max-width: 480px;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 1rem;
}

.person-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 1rem;
}

.person-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  text-decoration: none;
  color: var(--fg);
  background: var(--bg);
  transition: border-color 0.1s ease;
}
.person-card:hover {
  border-color: var(--accent);
}
.person-card-meta {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}
.person-card-alias {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Avatars (placeholder until M5) */
.avatar-placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  color: var(--muted);
  font-weight: 600;
  font-size: 1.1rem;
  flex-shrink: 0;
}

/* Tag chips */
.tag-chip-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.tag-chip {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 0.85rem;
  color: var(--muted);
}

/* Forms */
.form-section {
  max-width: 600px;
}
.person-form .form-row {
  margin-bottom: 1rem;
}
.person-form label {
  display: block;
  margin-bottom: 0.25rem;
  font-weight: 500;
}
.person-form input[type="text"],
.person-form input[type="search"] {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 1rem;
}
.form-help {
  margin: 0.25rem 0 0;
  color: var(--muted);
  font-size: 0.85rem;
}
.form-error {
  margin: 0.25rem 0 0;
  color: #b91c1c;
  font-size: 0.9rem;
}
.form-actions {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  margin-top: 1.5rem;
}
.btn-link {
  background: transparent;
  border: 0;
  color: var(--muted);
  text-decoration: underline;
  padding: 0.5rem;
}

/* Person detail */
.person-detail-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 2rem;
}
.person-detail-header .avatar-placeholder {
  width: 80px;
  height: 80px;
  font-size: 1.75rem;
}
.person-detail-meta {
  flex: 1;
  min-width: 0;
}
.person-detail-actions {
  display: flex;
  gap: 0.5rem;
}
.btn-disabled {
  background: var(--bg-soft);
  color: var(--muted);
  pointer-events: none;
}

/* Tag chip preview rendered by JS during typing */
#tag-chip-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.5rem;
}
#tag-chip-preview:empty {
  display: none;
}

/* Danger zone (delete person) */
.danger-zone {
  margin-top: 3rem;
  padding: 1rem;
  border: 1px solid #fecaca;
  border-radius: 8px;
  background: #fef2f2;
}
.danger-zone h3 {
  margin: 0 0 0.5rem;
  color: #b91c1c;
}
.delete-form {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}
.delete-form input[type="text"] {
  flex: 1;
  max-width: 320px;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.btn-danger {
  background: #b91c1c;
  color: white;
  border-color: #b91c1c;
}

/* Visually-hidden helper for accessible labels */
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0,0,0,0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 12.2: Create `flexlog/static/js/people_form.js`**

```javascript
// Live tag-chip preview while the user types in the tags field.
// Mirrors the server-side normalization: comma-separated, dedup case-insensitive.

(function () {
  "use strict";
  const tagsInput = document.getElementById("tags");
  if (!tagsInput) return;

  const preview = document.createElement("div");
  preview.id = "tag-chip-preview";
  preview.setAttribute("aria-hidden", "true");
  tagsInput.parentNode.appendChild(preview);

  function render() {
    const seen = new Set();
    const chips = [];
    for (const raw of tagsInput.value.split(",")) {
      const display = raw.trim();
      if (!display) continue;
      const key = display.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      const span = document.createElement("span");
      span.className = "tag-chip";
      span.textContent = display;
      chips.push(span);
    }
    preview.innerHTML = "";
    for (const c of chips) preview.appendChild(c);
  }

  tagsInput.addEventListener("input", render);
  render();
})();
```

- [ ] **Step 12.3: Add the `<script>` tag to both forms**

In both `flexlog/templates/people/new.html` and `flexlog/templates/people/edit.html`, add this after the closing `</form>`:

```jinja
<script src="{{ url_for('static', filename='js/people_form.js') }}" defer></script>
```

- [ ] **Step 12.4: Run tests, verify pass**

```bash
pytest -v
```

CSS and JS additions don't break tests. Coverage gate stays green.

- [ ] **Step 12.5: Commit**

```bash
git add flexlog/static/css/main.css flexlog/static/js/people_form.js \
        flexlog/templates/people/new.html flexlog/templates/people/edit.html
git commit -m "M2: add CSS for cards/chips/forms + tag chip preview JS

Inline JS mirrors the server's tag normalization (split, trim, dedup
case-insensitive) for instant feedback. Defer-loaded — no FOUC concerns.
Danger-zone styling for the delete form."
```

---

## Task 13: CSRF integration test + final sweep

**Files:**
- Create: `tests/integration/test_csrf.py`
- Modify: `README.md` (mention M2 features)

- [ ] **Step 13.1: Write the CSRF integration test**

`tests/integration/test_csrf.py`:

```python
def test_post_create_person_without_csrf_rejected(csrf_client):
    """With CSRF enabled, a POST without a valid token must be rejected."""
    resp = csrf_client.post("/people", data={"alias": "Alice", "tags": ""})
    # Flask-WTF returns 400 (or 403 depending on config) on CSRF failure
    assert resp.status_code in (400, 403)


def test_post_delete_person_without_csrf_rejected(csrf_client, csrf_app):
    """Even DELETE-on-POST routes need CSRF."""
    # We need a valid person id first. Create one inside the csrf_app context.
    from flexlog.db import close_db, get_db
    from flexlog.services.people import create_person

    with csrf_app.app_context():
        db = get_db()
        p = create_person(db, alias="Alice", tag_input="")
        db.commit()
        pid = p.id
        close_db()

    resp = csrf_client.post(f"/people/{pid}/delete", data={"confirm_alias": "Alice"})
    assert resp.status_code in (400, 403)
```

- [ ] **Step 13.2: Update `README.md`**

Find the "What's next" section and update it to:

```markdown
## What's next

Subsequent milestones:

- **M2 (✓ shipped):** people + tags + dashboard
- M3: sessions + ratings + notes
- M4: media + Media Library + hash dedup
- M5: avatar cropper + sort + polish

See `docs/superpowers/specs/2026-05-07-flexlog-design.md` §12 for the full
roadmap.
```

Also add a brief features section above the "Run the test suite" heading:

```markdown
## Features (M2)

- Add, edit, delete people (delete requires typing the alias)
- Global tags shared across all people
- Dashboard with search by alias or tag
- Default avatar placeholder (real avatar upload comes in M5)
```

- [ ] **Step 13.3: Run the full suite + smoke test**

```bash
pytest -v
```

Confirm all tests pass; coverage gate green; per-module coverage table reasonable (services/people, services/tags, db/models all ≥95% per spec §11.4 — these become critical-path with M2).

End-to-end smoke test:

```bash
SCRATCH=$(mktemp -d)
FLEXLOG_DATA_DIR="$SCRATCH" flexlog &
APP_PID=$!
sleep 1

# Dashboard renders
curl -s http://127.0.0.1:5050/ | grep -q "Interview Log" && echo "OK: dashboard"

# DB was created with M2 tables
sqlite3 "$SCRATCH/data/encounters.db" ".tables" | grep -q "person" && echo "OK: person table"
sqlite3 "$SCRATCH/data/encounters.db" ".tables" | grep -q "tag" && echo "OK: tag table"

# Secret key file with mode 0600
[ "$(stat -f %Lp "$SCRATCH/.secret_key")" = "600" ] && echo "OK: secret_key 0600"

# New-person form renders
curl -s http://127.0.0.1:5050/people/new | grep -q "Alias" && echo "OK: new person form"

kill $APP_PID 2>/dev/null
wait $APP_PID 2>/dev/null || true
rm -rf "$SCRATCH"
```

(macOS `stat -f %Lp` syntax. On Linux, swap for `stat -c %a`.)

Expected: 4 OK lines.

- [ ] **Step 13.4: Commit + tag**

```bash
git add tests/integration/test_csrf.py README.md
git commit -m "M2: add CSRF rejection test + update README with M2 feature list"
git tag m2-people-tags
```

---

## Self-review notes (post-write)

**Spec coverage check:**

| Spec section | Implemented in |
|---|---|
| §6.5 Dashboard (people grid, search, empty state, "new person") | Task 11 |
| §6.6 Person Detail (avatar placeholder, alias, tags, edit, delete, empty session list) | Task 10 |
| §6.7 Add/Edit Person (alias required, tags free-text) | Tasks 8 + 9 |
| §6.10 Delete Person — type alias confirmation | Task 10 |
| §7 person/tag/person_tag schema with cascades | Task 4 |
| §8 routes for /people/* and / | Tasks 9 + 10 + 11 |
| §9 CSRF on every mutating form, secret key | Tasks 2 + 5 + 13 |
| §11 testing — pytest with real SQLite + tmp filesystem, 85% gate, ≥95% on critical-path modules | Throughout |
| §12 M2 deliverable | All tasks |

**Cross-task type consistency:** `Person`, `Tag`, `PersonTag` defined in Task 4 and consumed in Tasks 5/6/7/9/10/11. `Base`, `make_engine`, `make_session_factory`, `attach_to_app`, `get_db`, `close_db` defined in Task 3/5 and consumed throughout. `slugify`, `normalize_tag_input`, `get_or_create_tag`, `list_all_tags`, `InvalidTagError` defined in Task 6 and consumed in Task 7. `create_person`, `get_person`, `list_people`, `search_people`, `update_person`, `delete_person`, `PersonNotFoundError` defined in Task 7 and consumed in Tasks 9/10/11. `PersonForm`, `ALIAS_MAX`, `TAGS_MAX` defined in Task 8 and consumed in Task 9. Endpoint names: `home.home` (preserved), `people.new`, `people.create`, `people.edit`, `people.update`, `people.detail`, `people.destroy` — referenced consistently. No drift.

**Placeholder scan:** No "TBD" / "TODO" / "implement later" left. Every step has runnable code or runnable command.

**Scope check:** M2 is bounded to people + tags (sessions, ratings, media, avatars deferred to M3-M5). Each task is a single TDD cycle; the largest tasks (5, 7, 11) split into Step-level micro-tasks under the bite-sized 2-5 minute target.

---

**End of M2 plan.**
