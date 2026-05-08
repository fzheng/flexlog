# flexlog M3 Sessions + Ratings + Notes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `Session` and `SessionLink` entities and full session CRUD per spec §6.6, §6.8, §6.9. Custom ratings render dynamically from `config.json`; values stored as a JSON object on the session row. Person-detail page shows the real session list (chronological, newest first). Dashboard person cards light up with last-session-date / session-count / average-overall-score aggregates. Media (photos/audio/video) and link thumbnails stay deferred to M4 — link manager in M3 supports URL + optional label only.

**Architecture:** Models plug into the existing SA `Base` from M2; cascades on `session.person_id` are FK-level. `services/sessions.py` mirrors `services/people.py`'s shape (one create/get/list/update/delete + a small custom-rating helper). The session form is a Flask-WTF `FlaskForm` with a `FieldList` of `LinkSubForm` for links; custom rating dimensions are read out of `request.form` directly by the route handler (rather than dynamically built into the form class) because they vary per `config.json` and the form-class approach makes per-request introspection painful. Dashboard aggregates are a single grouped query in `services/people.py:list_dashboard_rows`. The "Add Session" button on `people/detail.html` becomes wired (it's disabled in M2). `BUILTIN_UI_DEFAULTS` and `config.ui_strings` extend with M3 keys; no public-template wording is hardcoded.

**Tech Stack:** Python 3.11+, Flask 3.x, SQLAlchemy 2.x ORM, Flask-WTF, Jinja2, pytest, pytest-cov. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-05-07-flexlog-design.md` — §6.4 (custom rating handling), §6.6 (Person Detail with session list), §6.8 (Session Detail page), §6.9 (Add/Edit Session), §6.10 (Delete Session — single confirmation), §7 (data model: session, session_link), §8 (routes), §11 (testing), §12 (M3 scope), §13.1/.2 (PM defaults: `overall_score` required; deletes permanent after confirmation).

**M3 deliverable:** Starting from a fresh `FLEXLOG_DATA_DIR`, the user can:
- create a session for an existing person (date, overall_score, custom ratings from config, notes, optional links with URL+label)
- view the session detail page (alias header, score, ratings, notes preserved with newlines, link list, edit/delete buttons)
- edit the session (mutate every field, add/remove links)
- delete a session (single confirmation dialog)
- delete an individual link from within an existing session
- person-detail page shows all sessions chronologically (newest first) with date, score, custom-rating summary, notes preview, link count
- dashboard person cards show last-session date, total count, average overall score
- archived custom ratings (IDs stored in JSON but no longer enabled in config) render under a collapsed "Archived ratings" group
- Chinese / UTF-8 notes round-trip cleanly

---

## File structure

| Path | Purpose |
|---|---|
| `flexlog/db/models.py` | **Modify**: add `Session`, `SessionLink` models + indexes |
| `flexlog/services/sessions.py` | **Create**: CRUD + custom rating split (current vs archived) |
| `flexlog/services/people.py` | **Modify**: add `list_dashboard_rows()` returning Person + aggregates |
| `flexlog/web/forms.py` | **Modify**: add `SessionForm` with `FieldList` of `LinkSubForm` |
| `flexlog/web/sessions_bp.py` | **Create**: `/people/<id>/sessions/new`, `POST /people/<id>/sessions`, `/sessions/<id>`, `/sessions/<id>/edit`, `POST /sessions/<id>`, `POST /sessions/<id>/delete`, `POST /session_links/<link_id>/delete` |
| `flexlog/web/__init__.py` | **Modify**: register `sessions_bp` |
| `flexlog/web/filters.py` | **Modify**: extend `BUILTIN_UI_DEFAULTS` with M3 keys + add a `notes_preview` Jinja filter |
| `flexlog/templates/sessions/new.html` | **Create**: Add Session form |
| `flexlog/templates/sessions/edit.html` | **Create**: Edit Session form |
| `flexlog/templates/sessions/detail.html` | **Create**: Session Detail page |
| `flexlog/templates/_partials/session_row.html` | **Create**: One row in the session list (used by person-detail) |
| `flexlog/templates/_partials/link_row_form.html` | **Create**: Reusable link-row partial used in new/edit forms |
| `flexlog/templates/_partials/link_row_display.html` | **Create**: Reusable link-row partial used in detail view |
| `flexlog/templates/_partials/person_card.html` | **Modify**: render aggregates |
| `flexlog/templates/people/detail.html` | **Modify**: replace empty-state with real session list; wire Add Session button |
| `flexlog/templates/dashboard.html` | **Modify**: pass aggregate rows to person_card |
| `flexlog/web/dashboard_bp.py` | **Modify**: call `list_dashboard_rows()` |
| `flexlog/static/css/main.css` | **Append**: session-form, session-row, danger-zone-session, ratings-grid styles |
| `flexlog/static/js/session_form.js` | **Create**: clone-row JS for the link manager |
| `flexlog/static/js/sessions_links.js` | (none — combined into `session_form.js`) |
| `tests/unit/test_sessions_service.py` | **Create**: CRUD + custom-rating split + delete cascade |
| `tests/unit/test_dashboard_aggregates.py` | **Create**: aggregate query correctness |
| `tests/unit/test_session_models.py` | **Create**: cascade person→session→links; CHECK constraints |
| `tests/unit/test_forms_session.py` | **Create**: SessionForm field validation |
| `tests/integration/test_session_routes.py` | **Create**: full CRUD via test client |
| `tests/integration/test_session_links.py` | **Create**: link delete endpoint |
| `tests/integration/test_person_detail_with_sessions.py` | **Create**: person-detail now shows real list |
| `tests/integration/test_dashboard.py` | **Modify**: assert aggregate columns appear |
| `README.md` | **Modify**: M3 features section |

---

## Task 1: Add `Session` and `SessionLink` models

**Files:**
- Modify: `flexlog/db/models.py`
- Create: `tests/unit/test_session_models.py`

- [ ] **Step 1.1: Write failing tests**

`tests/unit/test_session_models.py`:

```python
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from flexlog.db import Base, make_engine, make_session_factory
from flexlog.db.models import Person, Session as SessionModel, SessionLink


@pytest.fixture
def session(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s


def _person(session, alias="Alice"):
    p = Person(id="p1", alias=alias)
    session.add(p)
    session.commit()
    return p


def test_create_all_registers_session_tables(tmp_path):
    db_path = tmp_path / "encounters.db"
    engine = make_engine(db_path)
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {"session", "session_link"} <= names


def test_can_insert_session(session):
    _person(session)
    s = SessionModel(
        id="s1",
        person_id="p1",
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings_json='{"clarity": 5}',
        notes="Good chat.",
    )
    session.add(s)
    session.commit()
    got = session.get(SessionModel, "s1")
    assert got is not None
    assert got.person_id == "p1"
    assert got.session_date == "2026-04-15"
    assert got.overall_score == 4
    assert got.custom_ratings_json == '{"clarity": 5}'
    assert got.notes == "Good chat."
    assert got.created_at is not None
    assert got.updated_at is not None


def test_session_overall_score_check_constraint(session):
    _person(session)
    bad = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=6)
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_session_overall_score_negative_rejected(session):
    _person(session)
    bad = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=-1)
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_session_session_date_required(session):
    _person(session)
    bad = SessionModel(id="s1", person_id="p1", session_date=None, overall_score=3)  # type: ignore[arg-type]
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_person_cascades_sessions(session):
    p = _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.commit()
    session.delete(p)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session")).scalar() == 0


def test_can_insert_session_link(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.commit()
    link = SessionLink(
        id="l1",
        session_id="s1",
        url="https://example.com",
        label="Reference",
        sort_order=0,
    )
    session.add(link)
    session.commit()
    got = session.get(SessionLink, "l1")
    assert got.url == "https://example.com"
    assert got.label == "Reference"
    assert got.thumbnail_media_id is None  # M4 layers the FK


def test_session_link_url_required(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.commit()
    bad = SessionLink(id="l1", session_id="s1", url=None)  # type: ignore[arg-type]
    session.add(bad)
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_session_cascades_links(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.add(SessionLink(id="l1", session_id="s1", url="https://example.com"))
    session.add(SessionLink(id="l2", session_id="s1", url="https://other.com"))
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 2
    session.delete(s)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 0


def test_deleting_person_cascades_through_session_to_links(session):
    p = _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.add(SessionLink(id="l1", session_id="s1", url="https://example.com"))
    session.commit()
    session.delete(p)
    session.commit()
    assert session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 0


def test_person_sessions_relationship_navigates(session):
    p = _person(session)
    session.add(SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3))
    session.add(SessionModel(id="s2", person_id="p1", session_date="2026-05-01", overall_score=4))
    session.commit()
    refreshed = session.get(Person, "p1")
    assert {s.id for s in refreshed.sessions} == {"s1", "s2"}


def test_session_links_relationship_navigates(session):
    _person(session)
    s = SessionModel(id="s1", person_id="p1", session_date="2026-04-15", overall_score=3)
    session.add(s)
    session.add(SessionLink(id="l1", session_id="s1", url="https://a.com", sort_order=1))
    session.add(SessionLink(id="l2", session_id="s1", url="https://b.com", sort_order=0))
    session.commit()
    refreshed = session.get(SessionModel, "s1")
    # Ordered by sort_order ascending
    assert [li.url for li in refreshed.links] == ["https://b.com", "https://a.com"]
```

- [ ] **Step 1.2: Run failing tests**

```bash
pytest tests/unit/test_session_models.py -v
```

Expected: ImportError on missing `Session`/`SessionLink`.

- [ ] **Step 1.3: Modify `flexlog/db/models.py`**

Append the following to the END of the file (after `PersonTag`). Also add a `Person.sessions` relationship — find the `Person` class definition and append the `sessions` `Mapped` line right after the `tags` relationship:

```python
    sessions: Mapped[List["Session"]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        order_by="Session.session_date.desc()",
    )
```

(`Person.tags` keeps its no-cascade comment; `Person.sessions` correctly cascades because deleting a person removes their sessions per spec §7.1 — and the spec's M3 deviation note about media-survives-delete only kicks in at M4.)

Then append the new model classes:

```python
from sqlalchemy import CheckConstraint, Index


class Session(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    person_id: Mapped[str] = mapped_column(
        String, ForeignKey("person.id", ondelete="CASCADE"), nullable=False
    )
    session_date: Mapped[str] = mapped_column(Text, nullable=False)  # YYYY-MM-DD
    overall_score: Mapped[int] = mapped_column(nullable=False)
    custom_ratings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_utcnow_iso, onupdate=_utcnow_iso
    )

    person: Mapped["Person"] = relationship(back_populates="sessions")
    links: Mapped[List["SessionLink"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionLink.sort_order",
    )

    __table_args__ = (
        CheckConstraint("overall_score >= 0 AND overall_score <= 5", name="ck_session_overall_score"),
        Index("ix_session_person_date", "person_id", "session_date"),
    )


class SessionLink(Base):
    __tablename__ = "session_link"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("session.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FK to media_file lands in M4. Free string for now.
    thumbnail_media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default=_utcnow_iso)

    session: Mapped["Session"] = relationship(back_populates="links")
```

If `CheckConstraint` and `Index` aren't already imported at the top of `flexlog/db/models.py`, add them to the existing `from sqlalchemy import ...` line.

- [ ] **Step 1.4: Run tests**

```bash
pytest -v
```

Expected: all 12 new tests pass; all 188 prior tests still pass; coverage gate green.

- [ ] **Step 1.5: Commit**

```bash
git add flexlog/db/models.py tests/unit/test_session_models.py
git commit -m "M3: add Session + SessionLink models with cascading delete

Person.sessions cascade='all, delete-orphan' (deleting a person removes
their sessions; tag joins remain unchanged). Session.links cascade in
turn so deleting a session removes its link rows. CHECK constraint on
overall_score 0..5; index on (person_id, session_date) for the
chronological list. thumbnail_media_id stays a free string until M4."
```

---

## Task 2: `services/sessions.py` — CRUD + custom-rating split

**Files:**
- Create: `flexlog/services/sessions.py`
- Create: `tests/unit/test_sessions_service.py`

- [ ] **Step 2.1: Write failing tests**

`tests/unit/test_sessions_service.py`:

```python
import json

import pytest

from flexlog.db.models import Person, Session as SessionModel
from flexlog.services.people import create_person
from flexlog.services.sessions import (
    SessionNotFoundError,
    create_session,
    delete_session,
    get_session,
    list_sessions_for_person,
    split_custom_ratings,
    update_session,
)


def _person(db_session, alias="Alice"):
    p = create_person(db_session, alias=alias, tag_input="")
    db_session.commit()
    return p


def test_create_session_minimal(db_session):
    p = _person(db_session)
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings={},
        notes=None,
        links=[],
    )
    db_session.commit()
    assert s.id
    assert s.person_id == p.id
    assert s.session_date == "2026-04-15"
    assert s.overall_score == 4
    assert s.notes is None
    assert s.links == []
    assert s.custom_ratings_json in ("{}", None) or s.custom_ratings_json == "{}"


def test_create_session_with_full_payload(db_session):
    p = _person(db_session)
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=5,
        custom_ratings={"clarity": 4, "depth": 3},
        notes="深入交流",  # Chinese — UTF-8 round-trip
        links=[
            {"url": "https://example.com", "label": "Reference"},
            {"url": "https://other.com", "label": ""},
        ],
    )
    db_session.commit()
    refreshed = get_session(db_session, s.id)
    assert refreshed.notes == "深入交流"
    assert json.loads(refreshed.custom_ratings_json) == {"clarity": 4, "depth": 3}
    urls = [li.url for li in refreshed.links]
    assert urls == ["https://example.com", "https://other.com"]


def test_create_session_alias_required_via_person_id(db_session):
    """Creating against a missing person id must error cleanly."""
    with pytest.raises(ValueError, match="person"):
        create_session(
            db_session,
            person_id="nope",
            session_date="2026-04-15",
            overall_score=3,
            custom_ratings={},
            notes=None,
            links=[],
        )


def test_create_session_score_out_of_range_rejected(db_session):
    p = _person(db_session)
    with pytest.raises(ValueError, match="overall_score"):
        create_session(
            db_session,
            person_id=p.id,
            session_date="2026-04-15",
            overall_score=6,
            custom_ratings={},
            notes=None,
            links=[],
        )
    with pytest.raises(ValueError, match="overall_score"):
        create_session(
            db_session,
            person_id=p.id,
            session_date="2026-04-15",
            overall_score=-1,
            custom_ratings={},
            notes=None,
            links=[],
        )


def test_create_session_date_format_validated(db_session):
    p = _person(db_session)
    with pytest.raises(ValueError, match="session_date"):
        create_session(
            db_session,
            person_id=p.id,
            session_date="04/15/2026",
            overall_score=3,
            custom_ratings={},
            notes=None,
            links=[],
        )


def test_create_session_drops_empty_link_rows(db_session):
    """Empty/whitespace link rows from the form must be skipped."""
    p = _person(db_session)
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=3,
        custom_ratings={},
        notes=None,
        links=[
            {"url": "  ", "label": ""},
            {"url": "", "label": "label only"},
            {"url": "https://kept.com", "label": ""},
        ],
    )
    db_session.commit()
    assert [li.url for li in s.links] == ["https://kept.com"]


def test_get_session_returns_none_when_missing(db_session):
    assert get_session(db_session, "nope") is None


def test_list_sessions_for_person_orders_newest_first(db_session):
    p = _person(db_session)
    create_session(db_session, person_id=p.id, session_date="2026-03-01", overall_score=3, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-05-01", overall_score=4, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-04-01", overall_score=5, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    rows = list_sessions_for_person(db_session, p.id)
    assert [s.session_date for s in rows] == ["2026-05-01", "2026-04-01", "2026-03-01"]


def test_list_sessions_for_person_empty(db_session):
    p = _person(db_session)
    assert list_sessions_for_person(db_session, p.id) == []


def test_update_session_changes_every_field(db_session):
    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={"clarity": 2}, notes="old", links=[{"url": "https://old.com", "label": "Old"}])
    db_session.commit()
    update_session(
        db_session,
        s.id,
        session_date="2026-05-20",
        overall_score=5,
        custom_ratings={"clarity": 4, "depth": 3},
        notes="new",
        links=[{"url": "https://new.com", "label": "New"}],
    )
    db_session.commit()
    refreshed = get_session(db_session, s.id)
    assert refreshed.session_date == "2026-05-20"
    assert refreshed.overall_score == 5
    assert json.loads(refreshed.custom_ratings_json) == {"clarity": 4, "depth": 3}
    assert refreshed.notes == "new"
    assert [li.url for li in refreshed.links] == ["https://new.com"]


def test_update_session_clearing_links(db_session):
    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[{"url": "https://a.com"}])
    db_session.commit()
    update_session(db_session, s.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    refreshed = get_session(db_session, s.id)
    assert refreshed.links == []


def test_update_session_missing_raises(db_session):
    with pytest.raises(SessionNotFoundError):
        update_session(db_session, "nope", session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[])


def test_delete_session_removes_row(db_session):
    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    delete_session(db_session, s.id)
    db_session.commit()
    assert get_session(db_session, s.id) is None


def test_delete_session_cascades_links(db_session):
    from sqlalchemy import text

    p = _person(db_session)
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=3, custom_ratings={}, notes=None, links=[{"url": "https://a.com"}, {"url": "https://b.com"}])
    db_session.commit()
    delete_session(db_session, s.id)
    db_session.commit()
    assert db_session.execute(text("SELECT COUNT(*) FROM session_link")).scalar() == 0


def test_delete_session_missing_raises(db_session):
    with pytest.raises(SessionNotFoundError):
        delete_session(db_session, "nope")


# split_custom_ratings: takes the stored JSON string and the current list of
# enabled rating dimensions, returns (current_pairs, archived_pairs).


def test_split_custom_ratings_only_current(db_session):
    """Stored values for currently-enabled IDs render in current; nothing archived."""
    enabled_ids = ["clarity", "depth"]
    stored = '{"clarity": 4, "depth": 3}'
    current, archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("clarity", 4), ("depth", 3)]
    assert archived == []


def test_split_custom_ratings_extras_archived(db_session):
    """Stored IDs no longer in config render under archived."""
    enabled_ids = ["clarity"]
    stored = '{"clarity": 4, "removed_dim": 2}'
    current, archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("clarity", 4)]
    assert archived == [("removed_dim", 2)]


def test_split_custom_ratings_missing_current_omitted(db_session):
    """Currently-enabled IDs with no stored value are NOT included in current."""
    enabled_ids = ["clarity", "depth"]
    stored = '{"clarity": 4}'
    current, archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("clarity", 4)]
    assert archived == []


def test_split_custom_ratings_handles_null_or_empty_json(db_session):
    enabled_ids = ["clarity"]
    assert split_custom_ratings(None, enabled_ids) == ([], [])
    assert split_custom_ratings("", enabled_ids) == ([], [])
    assert split_custom_ratings("{}", enabled_ids) == ([], [])


def test_split_custom_ratings_preserves_config_order(db_session):
    """Current pairs follow the order of enabled_ids, not insertion order in JSON."""
    enabled_ids = ["depth", "clarity"]
    stored = '{"clarity": 4, "depth": 3}'
    current, _archived = split_custom_ratings(stored, enabled_ids)
    assert current == [("depth", 3), ("clarity", 4)]
```

- [ ] **Step 2.2: Run failing tests**

```bash
pytest tests/unit/test_sessions_service.py -v
```

Expected: ImportError on missing module.

- [ ] **Step 2.3: Implement `flexlog/services/sessions.py`**

```python
"""Session CRUD + custom-rating split.

Sessions belong to a person and carry an overall_score (required, 0..5),
optional notes, optional custom-rating values (stored as a JSON object on
the row so the schema doesn't churn when the user adds/removes rating
dimensions in config.json), and zero or more SessionLinks (URL + optional
label; thumbnails defer to M4).

split_custom_ratings() is the read-side helper: given the stored JSON and
the currently enabled rating IDs from config, it returns (current_pairs,
archived_pairs) for the template to render.
"""

from __future__ import annotations

import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from flexlog.db.models import Person, Session as SessionRow, SessionLink

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SessionNotFoundError(LookupError):
    """Raised by update/delete when the target session id does not exist."""


def _validate_inputs(person: Person | None, session_date: str, overall_score: int) -> None:
    if person is None:
        raise ValueError("person not found for the given person_id")
    if not isinstance(session_date, str) or not _DATE_RE.match(session_date):
        raise ValueError(f"session_date must be ISO YYYY-MM-DD, got {session_date!r}")
    if not isinstance(overall_score, int) or not (0 <= overall_score <= 5):
        raise ValueError(f"overall_score must be an integer 0..5, got {overall_score!r}")


def _serialize_ratings(custom_ratings: dict[str, int]) -> str:
    """Coerce the dict into a deterministic JSON string."""
    return json.dumps(dict(sorted(custom_ratings.items())))


def _replace_links(db: Session, session_row: SessionRow, links: list[dict]) -> None:
    """Drop existing links and recreate from `links` (rows with URL+label).

    Empty/whitespace URLs are silently dropped — accommodates form submission
    of empty rows from the link manager.
    """
    session_row.links = []
    for i, link in enumerate(links):
        url = (link.get("url") or "").strip()
        if not url:
            continue
        label = (link.get("label") or "").strip() or None
        session_row.links.append(
            SessionLink(
                id=str(uuid.uuid4()),
                session_id=session_row.id,
                url=url,
                label=label,
                sort_order=i,
            )
        )


def create_session(
    db: Session,
    person_id: str,
    session_date: str,
    overall_score: int,
    custom_ratings: dict[str, int],
    notes: str | None,
    links: list[dict],
) -> SessionRow:
    """Create a Session row + its links. Caller commits."""
    person = db.get(Person, person_id)
    _validate_inputs(person, session_date, overall_score)

    session_row = SessionRow(
        id=str(uuid.uuid4()),
        person_id=person_id,
        session_date=session_date,
        overall_score=overall_score,
        custom_ratings_json=_serialize_ratings(custom_ratings),
        notes=(notes or None) if (notes is None or notes.strip() == "") else notes,
    )
    db.add(session_row)
    db.flush()
    _replace_links(db, session_row, links)
    return session_row


def get_session(db: Session, session_id: str) -> SessionRow | None:
    stmt = (
        select(SessionRow)
        .where(SessionRow.id == session_id)
        .options(selectinload(SessionRow.links), selectinload(SessionRow.person))
    )
    return db.execute(stmt).scalar_one_or_none()


def list_sessions_for_person(db: Session, person_id: str) -> list[SessionRow]:
    """All sessions for `person_id`, newest first."""
    stmt = (
        select(SessionRow)
        .where(SessionRow.person_id == person_id)
        .order_by(SessionRow.session_date.desc())
        .options(selectinload(SessionRow.links))
    )
    return list(db.execute(stmt).scalars())


def update_session(
    db: Session,
    session_id: str,
    session_date: str,
    overall_score: int,
    custom_ratings: dict[str, int],
    notes: str | None,
    links: list[dict],
) -> SessionRow:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    _validate_inputs(session_row.person, session_date, overall_score)
    session_row.session_date = session_date
    session_row.overall_score = overall_score
    session_row.custom_ratings_json = _serialize_ratings(custom_ratings)
    session_row.notes = notes if (notes and notes.strip()) else None
    _replace_links(db, session_row, links)
    return session_row


def delete_session(db: Session, session_id: str) -> None:
    session_row = get_session(db, session_id)
    if session_row is None:
        raise SessionNotFoundError(session_id)
    db.delete(session_row)


def split_custom_ratings(
    stored_json: str | None,
    enabled_ids: list[str],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Split stored ratings into (current, archived) per spec §6.4.

    `current` follows the order of `enabled_ids`; only IDs whose value is
    actually stored appear. `archived` is everything stored but absent
    from `enabled_ids`, in stored insertion order.
    """
    if not stored_json:
        return [], []
    try:
        stored = json.loads(stored_json)
    except (ValueError, TypeError):
        return [], []
    if not isinstance(stored, dict):
        return [], []
    enabled_set = set(enabled_ids)
    current: list[tuple[str, int]] = []
    for rid in enabled_ids:
        if rid in stored and isinstance(stored[rid], int):
            current.append((rid, stored[rid]))
    archived: list[tuple[str, int]] = []
    for rid, val in stored.items():
        if rid not in enabled_set and isinstance(val, int):
            archived.append((rid, val))
    return current, archived
```

- [ ] **Step 2.4: Run tests**

```bash
pytest -v
```

Expected: all 21 new tests pass; coverage gate green.

- [ ] **Step 2.5: Commit**

```bash
git add flexlog/services/sessions.py tests/unit/test_sessions_service.py
git commit -m "M3: add session service — CRUD + custom-rating split

create/update validate the FK person, ISO date, score range; normalize
notes (empty → None) and rebuild link rows from form-side dicts (empty
URLs dropped). split_custom_ratings(stored_json, enabled_ids) returns
(current, archived) for the template per spec §6.4."
```

---

## Task 3: Dashboard aggregates query in `services/people.py`

**Files:**
- Modify: `flexlog/services/people.py`
- Create: `tests/unit/test_dashboard_aggregates.py`

- [ ] **Step 3.1: Write failing tests**

`tests/unit/test_dashboard_aggregates.py`:

```python
import pytest

from flexlog.services.people import create_person, list_dashboard_rows
from flexlog.services.sessions import create_session


def test_dashboard_rows_empty(db_session):
    assert list_dashboard_rows(db_session, query="") == []


def test_dashboard_rows_person_with_no_sessions(db_session):
    """A person with no sessions still appears, with zero/None aggregates."""
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="")
    assert len(rows) == 1
    row = rows[0]
    assert row.person.alias == "Alice"
    assert row.session_count == 0
    assert row.last_session_date is None
    assert row.avg_overall_score is None


def test_dashboard_rows_aggregates(db_session):
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-03-01", overall_score=4, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=5, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-02-10", overall_score=3, custom_ratings={}, notes=None, links=[])
    db_session.commit()

    rows = list_dashboard_rows(db_session, query="")
    assert len(rows) == 1
    row = rows[0]
    assert row.session_count == 3
    assert row.last_session_date == "2026-04-15"
    assert row.avg_overall_score == 4.0  # (4+5+3)/3


def test_dashboard_rows_search_by_alias(db_session):
    a = create_person(db_session, alias="Alice", tag_input="")
    b = create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="alice")
    assert [r.person.alias for r in rows] == ["Alice"]


def test_dashboard_rows_search_by_tag(db_session):
    a = create_person(db_session, alias="Alice", tag_input="Engineer")
    b = create_person(db_session, alias="Bob", tag_input="Coach")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="engineer")
    assert [r.person.alias for r in rows] == ["Alice"]


def test_dashboard_rows_alphabetical_by_alias(db_session):
    create_person(db_session, alias="Charlie", tag_input="")
    create_person(db_session, alias="alice", tag_input="")  # lowercase
    create_person(db_session, alias="Bob", tag_input="")
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="")
    # Case-insensitive alpha order
    assert [r.person.alias for r in rows] == ["alice", "Bob", "Charlie"]


def test_dashboard_rows_does_not_double_count_with_tags(db_session):
    """A person with multiple tags must appear once with correct aggregates."""
    p = create_person(db_session, alias="Alice", tag_input="Engineer, Friend, Coach")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=4, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-05-01", overall_score=5, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    rows = list_dashboard_rows(db_session, query="")
    assert len(rows) == 1
    assert rows[0].session_count == 2  # NOT 6 (sessions × tags)
```

- [ ] **Step 3.2: Run failing tests**

Expected: ImportError on missing `list_dashboard_rows`.

- [ ] **Step 3.3: Modify `flexlog/services/people.py`**

Add at the top of the file (alongside other imports):

```python
from dataclasses import dataclass

from sqlalchemy import func
```

Replace:

```python
from flexlog.db.models import Person, PersonTag, Tag
```

with:

```python
from flexlog.db.models import Person, PersonTag, Session as SessionRow, Tag
```

Then append at the END of the file:

```python
@dataclass(frozen=True)
class DashboardRow:
    """One person's dashboard row with aggregates."""
    person: Person
    session_count: int
    last_session_date: str | None
    avg_overall_score: float | None


def list_dashboard_rows(session: Session, query: str) -> list[DashboardRow]:
    """Return DashboardRows: one per person, with session aggregates.

    Search semantics match search_people: empty query → all; non-empty →
    case-insensitive substring match on alias OR tag.name OR tag.slug.
    Aggregates computed in a single grouped query with LEFT JOIN through
    session — people with no sessions still appear (zero/None aggregates).
    """
    q = (query or "").strip()
    base = (
        select(
            Person,
            func.count(SessionRow.id).label("session_count"),
            func.max(SessionRow.session_date).label("last_session_date"),
            func.avg(SessionRow.overall_score).label("avg_overall_score"),
        )
        .outerjoin(SessionRow, SessionRow.person_id == Person.id)
        .group_by(Person.id)
        .order_by(Person.alias.collate("NOCASE"))
        .options(selectinload(Person.tags))
    )

    if q != "":
        like = f"%{q.lower()}%"
        # We need an EXISTS subquery here rather than another join: joining
        # through person_tag/tag would multiply rows before GROUP BY and
        # break aggregates (test_dashboard_rows_does_not_double_count_with_tags).
        from sqlalchemy import exists

        tag_match = (
            select(PersonTag.person_id)
            .join(Tag, Tag.id == PersonTag.tag_id)
            .where(
                PersonTag.person_id == Person.id,
                or_(Tag.name.ilike(like), Tag.slug.ilike(like)),
            )
        )
        base = base.where(or_(Person.alias.ilike(like), exists(tag_match)))

    out: list[DashboardRow] = []
    for person, count, last_date, avg_score in session.execute(base).all():
        out.append(
            DashboardRow(
                person=person,
                session_count=int(count or 0),
                last_session_date=last_date,
                avg_overall_score=float(avg_score) if avg_score is not None else None,
            )
        )
    return out
```

- [ ] **Step 3.4: Run tests**

```bash
pytest -v
```

Expected: all 7 new aggregate tests pass; existing tests still pass.

- [ ] **Step 3.5: Commit**

```bash
git add flexlog/services/people.py tests/unit/test_dashboard_aggregates.py
git commit -m "M3: add list_dashboard_rows() with per-person session aggregates

DashboardRow dataclass (person, session_count, last_session_date,
avg_overall_score). Tag-search is done via EXISTS subquery to avoid
join-multiplied rows before GROUP BY — covered by the multi-tag test."
```

---

## Task 4: SessionForm + LinkSubForm

**Files:**
- Modify: `flexlog/web/forms.py`
- Create: `tests/unit/test_forms_session.py`

- [ ] **Step 4.1: Append failing tests to `tests/unit/test_forms_session.py`**

```python
import pytest

from flexlog.web.forms import SessionForm


def _ctx(app, **form_kwargs):
    return app.test_request_context(method="POST", data=form_kwargs)


def test_session_form_minimal_valid(app):
    with _ctx(app, session_date="2026-04-15", overall_score="3"):
        form = SessionForm()
        assert form.validate(), form.errors


def test_session_form_session_date_required(app):
    with _ctx(app, session_date="", overall_score="3"):
        form = SessionForm()
        assert not form.validate()
        assert "session_date" in form.errors


def test_session_form_session_date_format(app):
    with _ctx(app, session_date="04/15/2026", overall_score="3"):
        form = SessionForm()
        assert not form.validate()
        assert "session_date" in form.errors


def test_session_form_overall_score_required(app):
    with _ctx(app, session_date="2026-04-15", overall_score=""):
        form = SessionForm()
        assert not form.validate()
        assert "overall_score" in form.errors


def test_session_form_overall_score_too_high(app):
    with _ctx(app, session_date="2026-04-15", overall_score="6"):
        form = SessionForm()
        assert not form.validate()
        assert "overall_score" in form.errors


def test_session_form_overall_score_negative(app):
    with _ctx(app, session_date="2026-04-15", overall_score="-1"):
        form = SessionForm()
        assert not form.validate()
        assert "overall_score" in form.errors


def test_session_form_notes_optional(app):
    with _ctx(app, session_date="2026-04-15", overall_score="3", notes=""):
        form = SessionForm()
        assert form.validate(), form.errors


def test_session_form_notes_max_length(app):
    long = "x" * 100_001
    with _ctx(app, session_date="2026-04-15", overall_score="3", notes=long):
        form = SessionForm()
        assert not form.validate()
        assert "notes" in form.errors
```

- [ ] **Step 4.2: Run failing tests**

Expected: ImportError on `SessionForm`.

- [ ] **Step 4.3: Modify `flexlog/web/forms.py`**

Append:

```python
import re

from wtforms import IntegerField, TextAreaField
from wtforms.validators import NumberRange, Regexp

NOTES_MAX = 100_000  # 100k chars; well above any realistic single-session note

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SessionForm(FlaskForm):
    session_date = StringField(
        "session_date",
        validators=[
            DataRequired(message="session_date is required"),
            Regexp(_DATE_RE, message="session_date must be ISO YYYY-MM-DD"),
        ],
    )
    overall_score = IntegerField(
        "overall_score",
        validators=[
            DataRequired(message="overall_score is required"),
            NumberRange(min=0, max=5, message="overall_score must be 0..5"),
        ],
    )
    notes = TextAreaField(
        "notes",
        validators=[Optional(), Length(max=NOTES_MAX)],
    )
```

(Note: link rows are NOT a `FieldList` here. The route handler reads them directly from `request.form.getlist("link_url")` and `request.form.getlist("link_label")` — simpler than a FieldList, gives full control over add/remove rows in JS.)

- [ ] **Step 4.4: Run tests**

```bash
pytest -v
```

Expected: all 8 new SessionForm tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add flexlog/web/forms.py tests/unit/test_forms_session.py
git commit -m "M3: add SessionForm with date/score/notes validators

Date is validated against ISO YYYY-MM-DD via regex; score is 0..5
NumberRange; notes ≤ 100_000 chars. Links travel as parallel arrays in
request.form (link_url[]/link_label[]) — simpler than FieldList for our
add/remove-row JS UX."
```

---

## Task 5: Sessions blueprint — new + create routes

**Files:**
- Create: `flexlog/web/sessions_bp.py`
- Modify: `flexlog/web/__init__.py`

- [ ] **Step 5.1: Implement `flexlog/web/sessions_bp.py` (new + create only — detail/edit/update/delete come in Tasks 6-7)**

```python
"""Session CRUD routes."""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from flexlog.db import get_db
from flexlog.services.people import get_person
from flexlog.services.sessions import (
    SessionNotFoundError,
    create_session,
    delete_session,
    get_session,
    split_custom_ratings,
    update_session,
)
from flexlog.web.forms import SessionForm

sessions_bp = Blueprint("sessions", __name__)


def _person_or_404(person_id: str):
    person = get_person(get_db(), person_id)
    if person is None:
        abort(404)
    return person


def _session_or_404(session_id: str):
    s = get_session(get_db(), session_id)
    if s is None:
        abort(404)
    return s


def _enabled_rating_dimensions():
    cfg = current_app.config["FLEXLOG"]
    return [r for r in cfg.ratings if r.enabled]


def _parse_custom_ratings_from_request() -> dict[str, int]:
    """Pull rating_<id> form fields, validate against enabled dimensions."""
    out: dict[str, int] = {}
    for dim in _enabled_rating_dimensions():
        raw = (request.form.get(f"rating_{dim.id}") or "").strip()
        if not raw:
            continue
        try:
            val = int(raw)
        except ValueError:
            continue
        if dim.scale_min <= val <= dim.scale_max:
            out[dim.id] = val
    return out


def _parse_links_from_request() -> list[dict]:
    """Read link_url[] / link_label[] parallel arrays into list[dict]."""
    urls = request.form.getlist("link_url")
    labels = request.form.getlist("link_label")
    out: list[dict] = []
    for i, url in enumerate(urls):
        label = labels[i] if i < len(labels) else ""
        out.append({"url": url, "label": label})
    return out


@sessions_bp.get("/people/<person_id>/sessions/new")
def new(person_id: str):
    person = _person_or_404(person_id)
    form = SessionForm()
    return render_template(
        "sessions/new.html",
        form=form,
        person=person,
        rating_dimensions=_enabled_rating_dimensions(),
        existing_ratings={},
        existing_links=[],
    )


@sessions_bp.post("/people/<person_id>/sessions")
def create(person_id: str):
    person = _person_or_404(person_id)
    form = SessionForm()
    rating_dimensions = _enabled_rating_dimensions()
    if not form.validate_on_submit():
        return render_template(
            "sessions/new.html",
            form=form,
            person=person,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_custom_ratings_from_request(),
            existing_links=_parse_links_from_request(),
        ), 400
    db = get_db()
    session_row = create_session(
        db,
        person_id=person.id,
        session_date=form.session_date.data,
        overall_score=form.overall_score.data,
        custom_ratings=_parse_custom_ratings_from_request(),
        notes=(form.notes.data or None),
        links=_parse_links_from_request(),
    )
    db.commit()
    return redirect(url_for("sessions.detail", session_id=session_row.id))


# Detail / edit / update / delete added in Tasks 6 + 7.
```

- [ ] **Step 5.2: Update `flexlog/web/__init__.py`**

```python
"""flexlog blueprints + Flask wiring helpers."""

from __future__ import annotations

from flask import Flask

from flexlog.web.dashboard_bp import dashboard_bp
from flexlog.web.people_bp import people_bp
from flexlog.web.sessions_bp import sessions_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(sessions_bp)
```

- [ ] **Step 5.3: Stub the `detail` route in `sessions_bp.py`**

The `create` redirect targets `sessions.detail` which doesn't exist yet. Add a stub at the end of `sessions_bp.py` (will be replaced fully in Task 6):

```python
@sessions_bp.get("/sessions/<session_id>")
def detail(session_id: str):
    """STUB — full implementation in Task 6."""
    s = _session_or_404(session_id)
    return f"<p>session {s.id} on {s.session_date}, score {s.overall_score}</p>", 200
```

- [ ] **Step 5.4: Run tests**

```bash
pytest -v
```

Expected: existing tests still pass; no new tests added in this task. Coverage gate green.

- [ ] **Step 5.5: Commit**

```bash
git add flexlog/web/sessions_bp.py flexlog/web/__init__.py
git commit -m "M3: scaffold sessions blueprint with new/create routes (+ detail stub)

Custom ratings parsed from request.form 'rating_<id>' keys against the
config's enabled dimensions. Links read as parallel link_url[]/link_label[]
arrays. Templates land in Task 8."
```

---

## Task 6: Sessions blueprint — detail + edit + update routes

**Files:**
- Modify: `flexlog/web/sessions_bp.py`
- Create: `tests/integration/test_session_routes.py`

- [ ] **Step 6.1: Replace the stub `detail` route + add `edit` + `update`**

In `flexlog/web/sessions_bp.py`, find the stub `detail` route and replace it (and add `edit`/`update` afterwards) with:

```python
@sessions_bp.get("/sessions/<session_id>")
def detail(session_id: str):
    s = _session_or_404(session_id)
    enabled_ids = [d.id for d in _enabled_rating_dimensions()]
    current, archived = split_custom_ratings(s.custom_ratings_json, enabled_ids)
    # Build display ratings with their dimension labels
    label_map = {d.id: d.label for d in _enabled_rating_dimensions()}
    current_with_labels = [(rid, label_map[rid], val) for rid, val in current]
    return render_template(
        "sessions/detail.html",
        person=s.person,
        session=s,
        current_ratings=current_with_labels,
        archived_ratings=archived,
    )


@sessions_bp.get("/sessions/<session_id>/edit")
def edit(session_id: str):
    s = _session_or_404(session_id)
    form = SessionForm(data={
        "session_date": s.session_date,
        "overall_score": s.overall_score,
        "notes": s.notes or "",
    })
    enabled_ids = [d.id for d in _enabled_rating_dimensions()]
    current_pairs, _archived = split_custom_ratings(s.custom_ratings_json, enabled_ids)
    existing_ratings = dict(current_pairs)
    existing_links = [{"url": li.url, "label": li.label or ""} for li in s.links]
    return render_template(
        "sessions/edit.html",
        form=form,
        person=s.person,
        session=s,
        rating_dimensions=_enabled_rating_dimensions(),
        existing_ratings=existing_ratings,
        existing_links=existing_links,
    )


@sessions_bp.post("/sessions/<session_id>")
def update(session_id: str):
    s = _session_or_404(session_id)
    form = SessionForm()
    rating_dimensions = _enabled_rating_dimensions()
    if not form.validate_on_submit():
        return render_template(
            "sessions/edit.html",
            form=form,
            person=s.person,
            session=s,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_custom_ratings_from_request(),
            existing_links=_parse_links_from_request(),
        ), 400
    db = get_db()
    try:
        update_session(
            db, session_id,
            session_date=form.session_date.data,
            overall_score=form.overall_score.data,
            custom_ratings=_parse_custom_ratings_from_request(),
            notes=(form.notes.data or None),
            links=_parse_links_from_request(),
        )
    except SessionNotFoundError:
        abort(404)
    db.commit()
    return redirect(url_for("sessions.detail", session_id=session_id))
```

- [ ] **Step 6.2: Write `tests/integration/test_session_routes.py`**

```python
def _make_person(db_session, alias="Alice", tags=""):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias=alias, tag_input=tags)
    db_session.commit()
    return p


def _make_session(db_session, person_id, **kwargs):
    from flexlog.services.sessions import create_session
    defaults = dict(
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings={},
        notes=None,
        links=[],
    )
    defaults.update(kwargs)
    s = create_session(db_session, person_id=person_id, **defaults)
    db_session.commit()
    return s


def test_get_new_session_form(client, db_session):
    p = _make_person(db_session)
    resp = client.get(f"/people/{p.id}/sessions/new")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert p.alias in body
    # Renders enabled rating dimensions from config.json (default has clarity + overall_quality)
    assert "Clarity" in body or "Overall Quality" in body


def test_get_new_session_form_404_when_person_missing(client):
    resp = client.get("/people/nope/sessions/new")
    assert resp.status_code == 404


def test_post_create_session_minimal(client, db_session):
    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "4"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/sessions/" in resp.headers["Location"]


def test_post_create_session_with_full_payload(client, db_session):
    from flexlog.db.models import Session as SessionRow
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={
            "session_date": "2026-04-15",
            "overall_score": "5",
            "notes": "深入的对话",
            "rating_clarity": "4",
            "rating_overall_quality": "5",
            "link_url": ["https://example.com", "https://other.com", ""],
            "link_label": ["Reference", "Followup", ""],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    rows = db_session.query(SessionRow).filter_by(person_id=p.id).all()
    assert len(rows) == 1
    sid = rows[0].id
    s = get_session(db_session, sid)
    assert s.notes == "深入的对话"
    # Empty link row dropped
    assert [li.url for li in s.links] == ["https://example.com", "https://other.com"]


def test_post_create_session_invalid_score_rerenders(client, db_session):
    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "2026-04-15", "overall_score": "9"},
    )
    assert resp.status_code == 400
    body = resp.get_data(as_text=True)
    assert "overall_score" in body.lower()


def test_post_create_session_missing_date_rerenders(client, db_session):
    p = _make_person(db_session)
    resp = client.post(
        f"/people/{p.id}/sessions",
        data={"session_date": "", "overall_score": "3"},
    )
    assert resp.status_code == 400


def test_get_session_detail(client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, custom_ratings={"clarity": 4}, notes="hello", links=[{"url": "https://example.com", "label": "Ref"}])
    resp = client.get(f"/sessions/{s.id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "2026-04-15" in body
    assert "hello" in body
    assert "https://example.com" in body
    # Custom rating renders
    assert "Clarity" in body  # label from the default config.json


def test_get_session_detail_404(client):
    resp = client.get("/sessions/nope")
    assert resp.status_code == 404


def test_get_session_edit_prefills(client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, notes="prefilled", links=[{"url": "https://x.com", "label": "X"}])
    resp = client.get(f"/sessions/{s.id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "prefilled" in body
    assert "https://x.com" in body


def test_post_update_session(client, db_session):
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    s = _make_session(db_session, p.id, overall_score=2, notes="old")
    resp = client.post(
        f"/sessions/{s.id}",
        data={
            "session_date": "2026-05-20",
            "overall_score": "5",
            "notes": "new",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db_session.expire_all()
    refreshed = get_session(db_session, s.id)
    assert refreshed.overall_score == 5
    assert refreshed.notes == "new"
    assert refreshed.session_date == "2026-05-20"


def test_post_update_session_404_when_missing(client):
    resp = client.post("/sessions/nope", data={"session_date": "2026-04-15", "overall_score": "3"})
    assert resp.status_code == 404


def test_xss_in_notes_is_escaped(client, db_session):
    p = _make_person(db_session)
    s = _make_session(db_session, p.id, notes="<script>alert(1)</script>")
    resp = client.get(f"/sessions/{s.id}")
    body = resp.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_archived_ratings_render_separately(client, db_session, app):
    """Stored ratings whose IDs are no longer in config show under archived."""
    import json
    from flexlog.services.sessions import create_session

    p = _make_person(db_session)
    create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=3,
        custom_ratings={"clarity": 4, "removed_dim": 2},  # removed_dim isn't in config
        notes=None,
        links=[],
    )
    db_session.commit()

    # In default config "clarity" is enabled but "removed_dim" is not.
    rows = db_session.query(__import__("flexlog.db.models", fromlist=["Session"]).Session).all()
    sid = rows[0].id
    resp = client.get(f"/sessions/{sid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Both rating IDs should appear, but in different sections (the template
    # uses a heading like "Archived ratings" for the latter group).
    assert "Clarity" in body  # current label
    assert "removed_dim" in body  # archived raw id
```

- [ ] **Step 6.3: Run tests**

```bash
pytest -v
```

Expected: all 12 new integration tests pass.

- [ ] **Step 6.4: Commit**

```bash
git add flexlog/web/sessions_bp.py tests/integration/test_session_routes.py
git commit -m "M3: add session detail/edit/update routes

detail/ split_custom_ratings reuses the spec §6.4 contract: enabled IDs
render in 'current' (with labels), unknown IDs in 'archived'. edit
prefills the form from existing data; update validates and falls back
to re-rendering on form errors."
```

---

## Task 7: Sessions blueprint — delete + link delete

**Files:**
- Modify: `flexlog/web/sessions_bp.py`
- Create: `tests/integration/test_session_links.py`
- Modify: `tests/integration/test_session_routes.py` (append delete tests)

- [ ] **Step 7.1: Append to `flexlog/web/sessions_bp.py`**

```python
@sessions_bp.post("/sessions/<session_id>/delete")
def destroy(session_id: str):
    s = _session_or_404(session_id)
    person_id = s.person_id
    db = get_db()
    try:
        delete_session(db, session_id)
    except SessionNotFoundError:
        abort(404)
    db.commit()
    flash(f"Deleted session from {s.session_date}.", "success")
    return redirect(url_for("people.detail", person_id=person_id))


@sessions_bp.post("/session_links/<link_id>/delete")
def link_destroy(link_id: str):
    from flexlog.db.models import SessionLink

    db = get_db()
    link = db.get(SessionLink, link_id)
    if link is None:
        abort(404)
    session_id = link.session_id
    db.delete(link)
    db.commit()
    return redirect(url_for("sessions.edit", session_id=session_id))
```

- [ ] **Step 7.2: Append delete tests to `tests/integration/test_session_routes.py`**

```python
def test_post_delete_session(client, db_session):
    from flexlog.services.sessions import get_session

    p = _make_person(db_session)
    s = _make_session(db_session, p.id)
    resp = client.post(f"/sessions/{s.id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    # Redirects to person detail
    assert f"/people/{p.id}" in resp.headers["Location"]
    assert get_session(db_session, s.id) is None


def test_post_delete_session_404(client):
    resp = client.post("/sessions/nope/delete")
    assert resp.status_code == 404


def test_delete_session_cascades_links(client, db_session):
    from sqlalchemy import text

    p = _make_person(db_session)
    s = _make_session(db_session, p.id, links=[{"url": "https://a.com"}, {"url": "https://b.com"}])
    client.post(f"/sessions/{s.id}/delete")
    db_session.expire_all()
    assert db_session.execute(text("SELECT COUNT(*) FROM session_link WHERE session_id = :sid"), {"sid": s.id}).scalar() == 0
```

- [ ] **Step 7.3: Write `tests/integration/test_session_links.py`**

```python
def _make(db_session, links):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(
        db_session,
        person_id=p.id,
        session_date="2026-04-15",
        overall_score=4,
        custom_ratings={},
        notes=None,
        links=links,
    )
    db_session.commit()
    return p, s


def test_delete_link_removes_only_that_row(client, db_session):
    from flexlog.db.models import SessionLink

    p, s = _make(db_session, [{"url": "https://a.com", "label": "A"}, {"url": "https://b.com", "label": "B"}])
    target = [li for li in s.links if li.url == "https://a.com"][0]
    other_id = [li.id for li in s.links if li.url == "https://b.com"][0]

    resp = client.post(f"/session_links/{target.id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    # Redirects to the session edit page
    assert f"/sessions/{s.id}/edit" in resp.headers["Location"]

    db_session.expire_all()
    assert db_session.get(SessionLink, target.id) is None
    assert db_session.get(SessionLink, other_id) is not None


def test_delete_link_404_when_missing(client):
    resp = client.post("/session_links/nope/delete")
    assert resp.status_code == 404
```

- [ ] **Step 7.4: Run tests**

Expected: all delete tests pass.

- [ ] **Step 7.5: Commit**

```bash
git add flexlog/web/sessions_bp.py tests/integration/test_session_routes.py tests/integration/test_session_links.py
git commit -m "M3: add session delete + per-link delete routes

POST /sessions/<id>/delete cascades through session_link via the
ON DELETE CASCADE FK and redirects to the person detail. POST
/session_links/<id>/delete removes a single link in-place during
session edit."
```

---

## Task 8: Session templates + link manager partials

**Files:**
- Create: `flexlog/templates/sessions/new.html`
- Create: `flexlog/templates/sessions/edit.html`
- Create: `flexlog/templates/sessions/detail.html`
- Create: `flexlog/templates/_partials/link_row_form.html`
- Create: `flexlog/templates/_partials/link_row_display.html`
- Create: `flexlog/templates/_partials/session_row.html`
- Modify: `flexlog/web/filters.py` (extend BUILTIN_UI_DEFAULTS + add notes_preview filter)

- [ ] **Step 8.1: Update `flexlog/web/filters.py`**

In the `BUILTIN_UI_DEFAULTS` dict, add the M3 keys (alongside the existing M1+M2 entries):

```python
    # M3
    "new_session": "New Session",
    "edit_session": "Edit Session",
    "delete_session": "Delete Session",
    "delete_session_confirm": "Delete this session? This cannot be undone.",
    "session_date_label": "Date",
    "overall_score_label": "Overall score",
    "custom_ratings_heading": "Ratings",
    "archived_ratings_heading": "Archived ratings",
    "notes_label": "Notes",
    "links_heading": "Links",
    "link_url_label": "URL",
    "link_label_label": "Label (optional)",
    "add_link": "Add link",
    "remove_link": "Remove",
    "no_links": "No links.",
    "no_notes": "No notes.",
    "session_count": "sessions",
    "last_session": "Last:",
    "avg_score": "Avg:",
    "no_matches_for": "No matches for",
    "delete_alias_did_not_match": "Alias did not match.",
```

(Keep the previously-added `no_matches_for` and `delete_alias_did_not_match` keys — they were added in the M2 followup. Don't duplicate.)

Then add a Jinja filter `notes_preview` registered alongside `ui`. Find the `app.jinja_env.filters["ui"] = ...` line in `flexlog/app.py` and add a sibling registration. But `notes_preview` is pure-string and doesn't need `current_app`, so we can put the function in `filters.py` and register it in `app.py`:

In `flexlog/web/filters.py` append:

```python
NOTES_PREVIEW_LEN = 80


def notes_preview(notes: str | None, length: int = NOTES_PREVIEW_LEN) -> str:
    """Truncate notes to `length` characters, adding ellipsis if cut.

    Returns an empty string if notes is None or whitespace-only. Newlines
    in the snippet collapse to spaces so the row stays single-line.
    """
    if not notes or not notes.strip():
        return ""
    s = " ".join(notes.split())
    if len(s) <= length:
        return s
    return s[:length].rstrip() + "…"
```

In `flexlog/app.py`, add a registration line right after the existing `app.jinja_env.filters["ui"] = ...` line:

```python
    from flexlog.web.filters import notes_preview
    app.jinja_env.filters["notes_preview"] = notes_preview
```

- [ ] **Step 8.2: Create `flexlog/templates/_partials/link_row_form.html`**

```jinja
{# One link row in the session form. Caller passes `index`, `url`, `label`, optional `link_id`. #}
<div class="link-row" data-link-row>
  <input type="url" name="link_url" placeholder="https://..." value="{{ url or '' }}" autocomplete="off">
  <input type="text" name="link_label" placeholder="{{ 'link_label_label' | ui }}" value="{{ label or '' }}" autocomplete="off">
  {% if link_id %}
    <button type="button" class="btn btn-link" data-remove-existing-link data-link-id="{{ link_id }}">{{ "remove_link" | ui }}</button>
  {% else %}
    <button type="button" class="btn btn-link" data-remove-link>{{ "remove_link" | ui }}</button>
  {% endif %}
</div>
```

- [ ] **Step 8.3: Create `flexlog/templates/_partials/link_row_display.html`**

```jinja
{# Read-only link row used on the session detail page. Caller passes `link`. #}
<li class="link-display">
  <a href="{{ link.url }}" target="_blank" rel="noopener noreferrer">
    {{ link.label or link.url }}
  </a>
  {% if link.label %}<span class="link-url-meta">{{ link.url }}</span>{% endif %}
</li>
```

- [ ] **Step 8.4: Create `flexlog/templates/_partials/session_row.html`**

```jinja
{# Single session row on the person detail page. Caller passes `session`. #}
<li class="session-row">
  <a class="session-row-link" href="{{ url_for('sessions.detail', session_id=session.id) }}">
    <header class="session-row-head">
      <time datetime="{{ session.session_date }}">{{ session.session_date }}</time>
      <span class="session-score">★ {{ session.overall_score }}/5</span>
    </header>
    {% if session.notes %}
    <p class="session-notes-preview">{{ session.notes | notes_preview }}</p>
    {% endif %}
    <footer class="session-row-foot">
      {% if session.links %}<span class="session-link-count">{{ session.links | length }} link{% if session.links|length != 1 %}s{% endif %}</span>{% endif %}
    </footer>
  </a>
</li>
```

- [ ] **Step 8.5: Create `flexlog/templates/sessions/new.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ "new_session" | ui }} — {{ person.alias }}{% endblock %}

{% block content %}
<section class="form-section">
  <h2>{{ "new_session" | ui }} — {{ person.alias }}</h2>
  <form method="post" action="{{ url_for('sessions.create', person_id=person.id) }}" class="session-form">
    {{ form.csrf_token }}
    {% include "sessions/_form_body.html" %}
    <div class="form-actions">
      <button type="submit" class="btn btn-primary">{{ "save" | ui }}</button>
      <a class="btn btn-link" href="{{ url_for('people.detail', person_id=person.id) }}">{{ "cancel" | ui }}</a>
    </div>
  </form>
</section>
<script src="{{ url_for('static', filename='js/session_form.js') }}" defer></script>
{% endblock %}
```

- [ ] **Step 8.6: Create `flexlog/templates/sessions/edit.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ "edit_session" | ui }} — {{ person.alias }}{% endblock %}

{% block content %}
<section class="form-section">
  <h2>{{ "edit_session" | ui }} — {{ person.alias }} ({{ session.session_date }})</h2>
  <form method="post" action="{{ url_for('sessions.update', session_id=session.id) }}" class="session-form">
    {{ form.csrf_token }}
    {% include "sessions/_form_body.html" %}
    <div class="form-actions">
      <button type="submit" class="btn btn-primary">{{ "save" | ui }}</button>
      <a class="btn btn-link" href="{{ url_for('sessions.detail', session_id=session.id) }}">{{ "cancel" | ui }}</a>
    </div>
  </form>

  <section class="danger-zone">
    <h3>{{ "delete_session" | ui }}</h3>
    <p>{{ "delete_session_confirm" | ui }}</p>
    <form method="post" action="{{ url_for('sessions.destroy', session_id=session.id) }}" onsubmit="return confirm('{{ \"delete_session_confirm\" | ui }}');">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <button type="submit" class="btn btn-danger">{{ "delete_session" | ui }}</button>
    </form>
  </section>
</section>
<script src="{{ url_for('static', filename='js/session_form.js') }}" defer></script>
{% endblock %}
```

- [ ] **Step 8.7: Create `flexlog/templates/sessions/_form_body.html`**

(Shared form body included by both new + edit.)

```jinja
<div class="form-row">
  <label for="session_date">{{ "session_date_label" | ui }}</label>
  <input type="date" id="session_date" name="session_date" value="{{ form.session_date.data or '' }}" required>
  {% for err in form.session_date.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
</div>

<div class="form-row">
  <label for="overall_score">{{ "overall_score_label" | ui }}</label>
  <input type="number" id="overall_score" name="overall_score" min="0" max="5" step="1" value="{{ form.overall_score.data if form.overall_score.data is not none else '' }}" required>
  {% for err in form.overall_score.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
</div>

{% if rating_dimensions %}
<fieldset class="form-row ratings-grid">
  <legend>{{ "custom_ratings_heading" | ui }}</legend>
  {% for dim in rating_dimensions %}
    <div class="rating-input">
      <label for="rating_{{ dim.id }}">{{ dim.label }}</label>
      <input type="number" id="rating_{{ dim.id }}" name="rating_{{ dim.id }}"
             min="{{ dim.scale_min }}" max="{{ dim.scale_max }}" step="1"
             value="{{ existing_ratings.get(dim.id, '') }}">
    </div>
  {% endfor %}
</fieldset>
{% endif %}

<div class="form-row">
  <label for="notes">{{ "notes_label" | ui }}</label>
  <textarea id="notes" name="notes" rows="6">{{ form.notes.data or '' }}</textarea>
  {% for err in form.notes.errors %}<p class="form-error">{{ err }}</p>{% endfor %}
</div>

<fieldset class="form-row links-row">
  <legend>{{ "links_heading" | ui }}</legend>
  <div id="link-rows" data-link-rows>
    {% for link in existing_links %}
      {% with index = loop.index0, url = link.url, label = link.label, link_id = link.get('id', '') %}
        {% include "_partials/link_row_form.html" %}
      {% endwith %}
    {% endfor %}
    {# Always render at least one empty row #}
    {% if not existing_links %}
      {% with index = 0, url = '', label = '', link_id = '' %}
        {% include "_partials/link_row_form.html" %}
      {% endwith %}
    {% endif %}
  </div>
  <button type="button" id="add-link-row" class="btn">{{ "add_link" | ui }}</button>
</fieldset>
```

- [ ] **Step 8.8: Create `flexlog/templates/sessions/detail.html`**

```jinja
{% extends "_base.html" %}

{% block title %}{{ session.session_date }} — {{ person.alias }}{% endblock %}

{% block content %}
<section class="session-detail">
  <header class="session-detail-header">
    <p class="breadcrumb"><a href="{{ url_for('people.detail', person_id=person.id) }}">{{ person.alias }}</a></p>
    <h2>{{ session.session_date }}</h2>
    <p class="session-detail-score">{{ "overall_score_label" | ui }}: <strong>{{ session.overall_score }}/5</strong></p>
    <div class="session-detail-actions">
      <a class="btn" href="{{ url_for('sessions.edit', session_id=session.id) }}">{{ "edit_session" | ui }}</a>
    </div>
  </header>

  {% if current_ratings %}
  <section class="ratings-display">
    <h3>{{ "custom_ratings_heading" | ui }}</h3>
    <ul>
      {% for rid, label, value in current_ratings %}
        <li>{{ label }}: <strong>{{ value }}</strong></li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  {% if archived_ratings %}
  <details class="ratings-display archived">
    <summary>{{ "archived_ratings_heading" | ui }}</summary>
    <ul>
      {% for rid, value in archived_ratings %}
        <li>{{ rid }}: <strong>{{ value }}</strong></li>
      {% endfor %}
    </ul>
  </details>
  {% endif %}

  <section class="notes-display">
    <h3>{{ "notes_label" | ui }}</h3>
    {% if session.notes %}
      <pre class="notes">{{ session.notes }}</pre>
    {% else %}
      <p class="empty-state">{{ "no_notes" | ui }}</p>
    {% endif %}
  </section>

  <section class="links-display">
    <h3>{{ "links_heading" | ui }}</h3>
    {% if session.links %}
      <ul class="link-list">
        {% for link in session.links %}
          {% include "_partials/link_row_display.html" %}
        {% endfor %}
      </ul>
    {% else %}
      <p class="empty-state">{{ "no_links" | ui }}</p>
    {% endif %}
  </section>
</section>
{% endblock %}
```

- [ ] **Step 8.9: Run tests**

```bash
pytest -v
```

Expected: existing route + form tests now pass against real templates (no longer the stub). Coverage gate green.

- [ ] **Step 8.10: Commit**

```bash
git add flexlog/templates/sessions/ flexlog/templates/_partials/link_row_form.html \
        flexlog/templates/_partials/link_row_display.html \
        flexlog/templates/_partials/session_row.html \
        flexlog/web/filters.py flexlog/app.py
git commit -m "M3: add session new/edit/detail templates + link/session partials

session form factored into _form_body.html shared by new+edit. notes
render via <pre> for newline preservation. Archived-ratings group
collapsed by default with <details>. notes_preview Jinja filter is
registered alongside the ui filter."
```

---

## Task 9: Update person detail to show real session list

**Files:**
- Modify: `flexlog/templates/people/detail.html`
- Modify: `flexlog/web/people_bp.py` (`detail` route now passes sessions)
- Create: `tests/integration/test_person_detail_with_sessions.py`

- [ ] **Step 9.1: Update `flexlog/web/people_bp.py:detail`**

Replace the existing `detail` view to load sessions:

```python
@people_bp.get("/<person_id>")
def detail(person_id: str):
    person = _person_or_404(person_id)
    from flexlog.services.sessions import list_sessions_for_person
    sessions = list_sessions_for_person(get_db(), person_id)
    return render_template("people/detail.html", person=person, sessions=sessions)
```

- [ ] **Step 9.2: Update `flexlog/templates/people/detail.html`**

Replace the `<section class="sessions-section">` block with:

```jinja
  <section class="sessions-section">
    <header class="sessions-section-header">
      <h3>{{ labels.session.plural }}</h3>
      <a class="btn btn-primary" href="{{ url_for('sessions.new', person_id=person.id) }}">{{ "add_session" | ui }}</a>
    </header>
    {% if sessions %}
      <ul class="session-list">
        {% for session in sessions %}
          {% include "_partials/session_row.html" %}
        {% endfor %}
      </ul>
    {% else %}
      <p class="empty-state">{{ "no_sessions_yet" | ui }}</p>
    {% endif %}
  </section>
```

(The "Add Session" button is no longer disabled. Find the existing disabled-button line at the top of the page and remove it — the button now lives in the sessions section header. If you prefer keeping it at the top, replace the `btn-disabled` version with the wired one.)

Also: locate and DELETE the disabled `<a class="btn btn-disabled" href="#" aria-disabled="true" title="Coming in M3">{{ "add_session" | ui }}</a>` line in the page header — it's now replaced by the header inside `.sessions-section`.

- [ ] **Step 9.3: Write `tests/integration/test_person_detail_with_sessions.py`**

```python
def test_person_detail_no_sessions_shows_empty_state(client, db_session):
    from flexlog.services.people import create_person
    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    resp = client.get(f"/people/{p.id}")
    body = resp.get_data(as_text=True)
    assert "No sessions yet" in body
    assert f"/people/{p.id}/sessions/new" in body  # Add Session button wired


def test_person_detail_lists_sessions_newest_first(client, db_session):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-03-01", overall_score=3, custom_ratings={}, notes="oldest", links=[])
    create_session(db_session, person_id=p.id, session_date="2026-05-01", overall_score=5, custom_ratings={}, notes="newest", links=[])
    create_session(db_session, person_id=p.id, session_date="2026-04-01", overall_score=4, custom_ratings={}, notes="middle", links=[])
    db_session.commit()

    resp = client.get(f"/people/{p.id}")
    body = resp.get_data(as_text=True)
    # All three dates appear
    assert "2026-03-01" in body
    assert "2026-04-01" in body
    assert "2026-05-01" in body
    # Order: newest first → 2026-05-01 appears before 2026-03-01 in the body
    pos_newest = body.find("2026-05-01")
    pos_oldest = body.find("2026-03-01")
    assert pos_newest < pos_oldest
    # Notes preview shows
    assert "newest" in body


def test_person_detail_session_card_links_to_session_detail(client, db_session):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    s = create_session(db_session, person_id=p.id, session_date="2026-04-15", overall_score=4, custom_ratings={}, notes=None, links=[])
    db_session.commit()
    resp = client.get(f"/people/{p.id}")
    assert f"/sessions/{s.id}" in resp.get_data(as_text=True)


def test_person_detail_session_card_link_count(client, db_session):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(
        db_session, person_id=p.id, session_date="2026-04-15", overall_score=4,
        custom_ratings={}, notes=None,
        links=[{"url": "https://a.com"}, {"url": "https://b.com"}],
    )
    db_session.commit()
    resp = client.get(f"/people/{p.id}")
    body = resp.get_data(as_text=True)
    assert "2 link" in body  # "2 links"
```

- [ ] **Step 9.4: Run tests**

Expected: all 4 new tests pass; the M2 person-detail test (`test_get_person_detail`) still passes — it asserts "No sessions yet" copy which the new empty-state preserves.

- [ ] **Step 9.5: Commit**

```bash
git add flexlog/web/people_bp.py flexlog/templates/people/detail.html \
        tests/integration/test_person_detail_with_sessions.py
git commit -m "M3: wire person detail to real session list

Add Session button is no longer disabled; clicking takes the user to
/people/<id>/sessions/new. Session list ordered newest-first via the
service, notes preview truncated, link count shown."
```

---

## Task 10: Dashboard person card with aggregates

**Files:**
- Modify: `flexlog/web/dashboard_bp.py`
- Modify: `flexlog/templates/dashboard.html`
- Modify: `flexlog/templates/_partials/person_card.html`
- Modify: `tests/integration/test_dashboard.py` (extend)

- [ ] **Step 10.1: Update `flexlog/web/dashboard_bp.py`**

```python
"""Dashboard route (root /)."""

from __future__ import annotations

from flask import Blueprint, render_template, request

from flexlog.db import get_db
from flexlog.services.people import list_dashboard_rows

dashboard_bp = Blueprint("home", __name__)


@dashboard_bp.get("/")
def home():
    query = request.args.get("q", "").strip()
    rows = list_dashboard_rows(get_db(), query)
    return render_template("dashboard.html", rows=rows, query=query)
```

- [ ] **Step 10.2: Update `flexlog/templates/dashboard.html`**

Replace the `{% if people %}` ... block with:

```jinja
  {% if rows %}
    <ul class="person-grid">
      {% for row in rows %}
        <li>{% with person = row.person %}{% include "_partials/person_card.html" %}{% endwith %}</li>
      {% endfor %}
    </ul>
  {% elif query %}
    <p class="empty-state">{{ "no_matches_for" | ui }} &ldquo;{{ query }}&rdquo;.</p>
  {% else %}
    <p class="empty-state">{{ "empty_dashboard" | ui }}</p>
  {% endif %}
```

(`{% with %}` pushes `person` into scope so the existing person_card include keeps working without modification — the partial expects a `person` var.)

- [ ] **Step 10.3: Update `flexlog/templates/_partials/person_card.html`**

Replace with:

```jinja
{# Renders one person card. Caller passes `person` and optionally `row` (for aggregates). #}
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
    {% if row is defined and row %}
      <p class="person-card-stats">
        <span>{{ row.session_count }} {{ "session_count" | ui }}</span>
        {% if row.last_session_date %}<span>{{ "last_session" | ui }} {{ row.last_session_date }}</span>{% endif %}
        {% if row.avg_overall_score is not none %}<span>{{ "avg_score" | ui }} {{ "%.1f"|format(row.avg_overall_score) }}/5</span>{% endif %}
      </p>
    {% endif %}
  </div>
</a>
```

(Need to also pass `row` into the partial. Update the dashboard template's include site to push both `row` and `person`. The cleanest way: replace the `{% with person = row.person %}` from Step 10.2 with `{% with person = row.person, row = row %}`.)

- [ ] **Step 10.4: Update `tests/integration/test_dashboard.py`**

Append:

```python
def test_dashboard_shows_session_aggregates(client, db_session):
    from flexlog.services.people import create_person
    from flexlog.services.sessions import create_session

    p = create_person(db_session, alias="Alice", tag_input="")
    db_session.commit()
    create_session(db_session, person_id=p.id, session_date="2026-04-01", overall_score=4, custom_ratings={}, notes=None, links=[])
    create_session(db_session, person_id=p.id, session_date="2026-05-01", overall_score=5, custom_ratings={}, notes=None, links=[])
    db_session.commit()

    resp = client.get("/")
    body = resp.get_data(as_text=True)
    # Session count
    assert "2 sessions" in body or "2 session" in body
    # Last session date
    assert "2026-05-01" in body
    # Average overall score (4+5)/2 = 4.5
    assert "4.5" in body
```

- [ ] **Step 10.5: Run tests**

Expected: all dashboard tests still pass + the new aggregate test passes.

- [ ] **Step 10.6: Commit**

```bash
git add flexlog/web/dashboard_bp.py flexlog/templates/dashboard.html \
        flexlog/templates/_partials/person_card.html \
        tests/integration/test_dashboard.py
git commit -m "M3: dashboard cards show session count, last date, avg score

Per-person aggregates from list_dashboard_rows() render below tag chips.
Empty-aggregates branch (people with no sessions) still appears, just
without the stats line."
```

---

## Task 11: CSS additions + session_form.js (link row clone)

**Files:**
- Modify: `flexlog/static/css/main.css`
- Create: `flexlog/static/js/session_form.js`

- [ ] **Step 11.1: Append to `flexlog/static/css/main.css`**

```css
/* M3 — sessions */

.session-form fieldset {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  margin: 0 0 1rem;
}
.session-form fieldset > legend {
  padding: 0 0.5rem;
  font-weight: 500;
}
.ratings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.5rem 1rem;
}
.ratings-grid .rating-input label {
  display: block;
  font-size: 0.9rem;
  color: var(--muted);
}
.ratings-grid .rating-input input[type="number"] {
  width: 100%;
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 6px;
}

.session-form textarea {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  font: inherit;
  font-size: 1rem;
  resize: vertical;
}

.link-row {
  display: grid;
  grid-template-columns: 2fr 1fr auto;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.link-row input[type="url"],
.link-row input[type="text"] {
  padding: 0.4rem 0.6rem;
  border: 1px solid var(--border);
  border-radius: 6px;
}

/* Session list on person detail */
.session-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.session-row {
  border: 1px solid var(--border);
  border-radius: 8px;
}
.session-row-link {
  display: block;
  padding: 0.75rem 1rem;
  text-decoration: none;
  color: inherit;
}
.session-row-link:hover {
  background: var(--bg-soft);
}
.session-row-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-weight: 600;
}
.session-score {
  color: var(--muted);
}
.session-notes-preview {
  margin: 0.25rem 0;
  color: var(--muted);
}
.session-row-foot {
  font-size: 0.85rem;
  color: var(--muted);
}
.sessions-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

/* Person card stats */
.person-card-stats {
  margin: 0.25rem 0 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  font-size: 0.85rem;
  color: var(--muted);
}

/* Session detail */
.session-detail-header h2 {
  margin: 0 0 0.25rem;
}
.breadcrumb {
  margin: 0;
  font-size: 0.9rem;
  color: var(--muted);
}
.session-detail-score {
  margin: 0.25rem 0 1rem;
}
.notes {
  white-space: pre-wrap;
  font: inherit;
  margin: 0;
  padding: 0.5rem 0.75rem;
  background: var(--bg-soft);
  border-radius: 6px;
  border: 1px solid var(--border);
}
.link-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.link-display {
  margin-bottom: 0.5rem;
}
.link-url-meta {
  display: block;
  font-size: 0.85rem;
  color: var(--muted);
}
.ratings-display ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1.5rem;
}
.ratings-display.archived summary {
  cursor: pointer;
  color: var(--muted);
}
```

- [ ] **Step 11.2: Create `flexlog/static/js/session_form.js`**

```javascript
// Session form — link row management.
// Adds rows by cloning the first existing row; removes rows by clicking the
// per-row remove button. For pre-existing links (with data-link-id), the
// remove button POSTs to /session_links/<id>/delete instead of just hiding
// the row, so the deletion is persisted immediately.

(function () {
  "use strict";
  const rowsContainer = document.querySelector("[data-link-rows]");
  const addBtn = document.getElementById("add-link-row");
  if (!rowsContainer || !addBtn) return;

  function emptyRowFromTemplate() {
    const first = rowsContainer.querySelector(".link-row");
    if (!first) return null;
    const clone = first.cloneNode(true);
    clone.querySelectorAll("input").forEach((i) => (i.value = ""));
    // New rows are NOT existing-link removes — remove the data-link-id, swap
    // the button data attr.
    clone.querySelectorAll("[data-remove-existing-link]").forEach((b) => {
      b.removeAttribute("data-remove-existing-link");
      b.removeAttribute("data-link-id");
      b.setAttribute("data-remove-link", "");
    });
    return clone;
  }

  function ensureAtLeastOneRow() {
    if (rowsContainer.querySelectorAll(".link-row").length === 0) {
      const fresh = emptyRowFromTemplate();
      if (fresh) rowsContainer.appendChild(fresh);
    }
  }

  addBtn.addEventListener("click", () => {
    const fresh = emptyRowFromTemplate();
    if (fresh) rowsContainer.appendChild(fresh);
  });

  rowsContainer.addEventListener("click", (event) => {
    const removeBtn = event.target.closest("[data-remove-link]");
    if (removeBtn) {
      removeBtn.closest(".link-row").remove();
      ensureAtLeastOneRow();
      return;
    }
    const removeExisting = event.target.closest("[data-remove-existing-link]");
    if (removeExisting) {
      const linkId = removeExisting.getAttribute("data-link-id");
      if (!linkId) return;
      // POST to /session_links/<id>/delete using a hidden synthetic form so
      // the request carries the page's CSRF token.
      const form = document.createElement("form");
      form.method = "post";
      form.action = "/session_links/" + encodeURIComponent(linkId) + "/delete";
      const csrfInput = document.querySelector("input[name='csrf_token']");
      if (csrfInput) {
        const tok = document.createElement("input");
        tok.type = "hidden";
        tok.name = "csrf_token";
        tok.value = csrfInput.value;
        form.appendChild(tok);
      }
      document.body.appendChild(form);
      form.submit();
    }
  });
})();
```

- [ ] **Step 11.3: Run tests**

```bash
pytest -v
```

Expected: all tests still pass; CSS/JS additions don't affect test outcomes.

- [ ] **Step 11.4: Commit**

```bash
git add flexlog/static/css/main.css flexlog/static/js/session_form.js
git commit -m "M3: CSS for session form/list/detail + link-row management JS

Session-form ratings render in a responsive grid; link rows can be
added by cloning the first row and removed with the per-row button. For
pre-existing links the remove button POSTs to /session_links/<id>/delete
so the deletion persists without waiting for the form save."
```

---

## Task 12: Final sweep — README, smoke, tag

**Files:**
- Modify: `README.md`
- Run final smoke

- [ ] **Step 12.1: Update `README.md`**

Find the "## Features (M2)" heading and replace the section with:

```markdown
## Features (M3)

- Add, edit, delete people (delete requires typing the alias)
- Global tags shared across all people
- Dashboard with search by alias or tag, plus per-person session count, last
  session date, and average overall score
- Sessions per person: required date + 0..5 overall score, custom rating
  dimensions from `config.json`, plain-text notes (UTF-8 / Chinese OK), and
  zero or more links (URL + optional label)
- Archived custom ratings — values stored under rating IDs no longer in
  `config.json` render under a collapsed "Archived ratings" group
- Default avatar placeholder (real avatar upload comes in M5)
- Media uploads (photos, audio, video) come in M4
```

Find the "## What's next" section and update it to:

```markdown
## What's next

Subsequent milestones:

- **M2 (✓ shipped):** people + tags + dashboard
- **M3 (✓ shipped):** sessions + ratings + notes + dashboard aggregates
- M4: media + Media Library + hash dedup
- M5: avatar cropper + sort + polish

See `docs/superpowers/specs/2026-05-07-flexlog-design.md` §12 for the full
roadmap.
```

- [ ] **Step 12.2: Run the full pytest suite + smoke test**

```bash
make test
make smoke
```

The smoke target should still print 3 OK lines (dashboard 200, .secret_key, encounters.db). Tests should hit ≥250 (M2 was 188 + M3 adds ~70).

- [ ] **Step 12.3: Commit + tag**

```bash
git add README.md
git commit -m "M3: update README with sessions feature list and roadmap"
git tag m3-sessions
```

## Report

- Status
- Final test count + per-module coverage table
- Total coverage %
- Smoke test output
- Concerns

---

## Self-review notes

**Spec coverage check:**

| Spec section | Implemented in |
|---|---|
| §6.4 custom rating handling (current vs archived) | Tasks 2 + 6 + 8 |
| §6.6 person detail with session list | Task 9 |
| §6.8 session detail page (notes, ratings, links) | Tasks 6 + 8 |
| §6.9 add/edit session form (date, score, ratings, notes, links) | Tasks 4 + 5 + 6 + 8 |
| §6.10 delete session — single confirmation | Task 7 + edit template |
| §7 session, session_link models with cascades | Task 1 |
| §8 routes /people/<id>/sessions/new, /sessions/<id>, /session_links/<id>/delete | Tasks 5 + 6 + 7 |
| §11 testing — pytest + ≥85% gate, ≥95% on critical paths | Throughout |
| §12 M3 deliverable + dashboard aggregates lit up | Tasks 3 + 10 |

**Cross-task consistency:** `Session`, `SessionLink` defined in Task 1 and consumed in Tasks 2, 3, 6, 7. `create_session`, `get_session`, `list_sessions_for_person`, `update_session`, `delete_session`, `split_custom_ratings`, `SessionNotFoundError` defined in Task 2 and consumed in Tasks 5, 6, 7, 9, 10, integration tests. `DashboardRow`, `list_dashboard_rows` defined in Task 3 and consumed in Task 10. `SessionForm` defined in Task 4 and consumed in Tasks 5, 6. Endpoint names: `sessions.new`, `sessions.create`, `sessions.detail`, `sessions.edit`, `sessions.update`, `sessions.destroy`, `sessions.link_destroy` referenced consistently. Routes: `/people/<id>/sessions/new` (POST + GET), `/sessions/<id>` (GET + POST), `/sessions/<id>/edit`, `/sessions/<id>/delete`, `/session_links/<id>/delete` per spec §8.

**Placeholder scan:** No "TBD" / "TODO" / "implement later". Every step has runnable code or commands.

**Scope check:** M3 is bounded to sessions/ratings/notes (media in M4, avatar cropper in M5). The "Add Session" button gets wired; "Add media to session" stays absent until M4 (no UI affordance for it; the form has no file inputs).

---

**End of M3 plan.**
