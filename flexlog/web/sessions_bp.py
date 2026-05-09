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
from flexlog.db.models import SessionLink
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


def _gather_uploads() -> list:
    """Gather all uploaded files from photos[], audios[], videos[] into one list."""
    out = []
    for name in ("photos", "audios", "videos"):
        for fs in request.files.getlist(name):
            if fs and fs.filename:
                out.append(fs)
    return out


def _gather_link_thumbnails() -> list:
    """Read link_thumbnail[] file inputs (parallel to link_url[]/link_label[])."""
    return list(request.files.getlist("link_thumbnail"))


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
        media_uploads=_gather_uploads(),
        link_thumbnails=_gather_link_thumbnails(),
    )
    db.commit()
    return redirect(url_for("sessions.detail", session_id=session_row.id))


# Detail / edit / update / delete added in Tasks 6 + 7.


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
            media_uploads=_gather_uploads(),
            link_thumbnails=_gather_link_thumbnails(),
            remove_session_media_ids=request.form.getlist("remove_session_media"),
            clear_link_thumbnail_link_ids=request.form.getlist("clear_link_thumbnail"),
        )
    except SessionNotFoundError:
        abort(404)
    db.commit()
    return redirect(url_for("sessions.detail", session_id=session_id))


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
    db = get_db()
    link = db.get(SessionLink, link_id)
    if link is None:
        abort(404)
    session_id = link.session_id
    db.delete(link)
    db.commit()
    return redirect(url_for("sessions.edit", session_id=session_id))
