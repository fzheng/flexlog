"""Session CRUD routes."""

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

from sqlalchemy import select

from flexlog.db import get_db
from flexlog.db.models import MediaFile, SessionLink
from flexlog.services.people import get_person
from flexlog.services.sessions import (
    SessionNotFoundError,
    compute_overall,
    create_session,
    delete_session,
    enabled_rating_dimensions,
    get_session,
    link_media_to_session,
    split_ratings,
    unlink_media_from_session,
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


def _parse_ratings_from_request() -> dict[str, int]:
    """Pull rating_<id> form fields. Values are clamped to [0, 5]
    (defensive — the star UI can't send out-of-range, but a direct POST
    bypass shouldn't crash the save)."""
    out: dict[str, int] = {}
    for dim in enabled_rating_dimensions():
        raw = (request.form.get(f"rating_{dim.id}") or "").strip()
        if not raw:
            continue
        try:
            val = int(raw)
        except ValueError:
            continue
        if val < 0:
            val = 0
        elif val > 5:
            val = 5
        out[dim.id] = val
    return out


def _parse_link_urls_from_request() -> list[str]:
    """Read link_urls[] in submitted order, drop blanks. The parallel
    list of thumb-keys is preserved alongside via
    _parse_link_thumb_keys_from_request — keep both helpers in sync if
    you change one."""
    return [u for u in request.form.getlist("link_urls") if (u or "").strip()]


def _parse_link_thumb_keys_from_request() -> list[str]:
    """Read link_thumb_keys[] in the same order as link_urls[], dropping
    keys at positions whose URL is blank. The two lists must stay
    aligned for `_replace_links` to pair them correctly."""
    urls = request.form.getlist("link_urls")
    keys = request.form.getlist("link_thumb_keys")
    while len(keys) < len(urls):
        keys.append("")
    return [k for u, k in zip(urls, keys) if (u or "").strip()]


def _build_existing_links_for_template(urls: list[str], keys: list[str]) -> list[dict]:
    """Build the list of dicts the form template iterates: each entry
    has url, thumb_key, and thumb_url (the rendered <img> src, or '').
    Used by both the GET edit path (from session.links) and the form
    re-render path (from the just-submitted form data)."""
    db = get_db()
    if len(keys) < len(urls):
        keys = list(keys) + [""] * (len(urls) - len(keys))
    nonempty = {(k or "").strip() for k in keys if (k or "").strip()}
    mf_by_key: dict[str, MediaFile] = {}
    if nonempty:
        mf_by_key = {
            mf.file_key: mf
            for mf in db.execute(
                select(MediaFile).where(MediaFile.file_key.in_(nonempty))
            ).scalars()
            if mf.media_type == "photo"
        }
    rows = []
    for u, k in zip(urls, keys):
        url = (u or "").strip()
        if not url:
            continue
        key = (k or "").strip()
        if key and key in mf_by_key:
            rows.append({
                "url": url,
                "thumb_key": key,
                "thumb_url": url_for("media.serve", file_key=key),
            })
        else:
            rows.append({"url": url, "thumb_key": "", "thumb_url": ""})
    return rows


def _parse_keys_from_request() -> dict[str, list[str]]:
    return {
        "photo": request.form.getlist("photo_keys"),
        "audio": request.form.getlist("audio_keys"),
        "video": request.form.getlist("video_keys"),
    }


def _parse_unlinked_keys_from_request() -> list[str]:
    return request.form.getlist("unlinked_keys")


@sessions_bp.get("/people/<person_id>/sessions/new")
def new(person_id: str):
    person = _person_or_404(person_id)
    form = SessionForm()
    return render_template(
        "sessions/new.html",
        form=form,
        person=person,
        rating_dimensions=enabled_rating_dimensions(),
        existing_ratings={},
        existing_links=[],
        existing_media={"photo": [], "audio": [], "video": []},
    )


@sessions_bp.post("/people/<person_id>/sessions")
def create(person_id: str):
    person = _person_or_404(person_id)
    form = SessionForm()
    rating_dimensions = enabled_rating_dimensions()
    submitted_link_urls = _parse_link_urls_from_request()
    submitted_link_thumb_keys = _parse_link_thumb_keys_from_request()
    if not form.validate_on_submit():
        return render_template(
            "sessions/new.html",
            form=form,
            person=person,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_ratings_from_request(),
            existing_links=_build_existing_links_for_template(
                submitted_link_urls, submitted_link_thumb_keys
            ),
            existing_media={"photo": [], "audio": [], "video": []},
        ), 400
    db = get_db()
    session_row = create_session(
        db,
        person_id=person.id,
        session_date=form.session_date.data,
        ratings=_parse_ratings_from_request(),
        notes=(form.notes.data or None),
        link_urls=submitted_link_urls,
        link_thumb_keys=submitted_link_thumb_keys,
    )
    _created, unknown = link_media_to_session(
        db, session_row.id, _parse_keys_from_request()
    )
    if unknown:
        db.rollback()
        flash(
            "Some uploaded files are no longer available "
            f"({len(unknown)} stale key{'s' if len(unknown) != 1 else ''}). "
            "Remove the marked rows and try again.",
            "error",
        )
        return render_template(
            "sessions/new.html",
            form=form,
            person=person,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_ratings_from_request(),
            existing_links=_build_existing_links_for_template(
                submitted_link_urls, submitted_link_thumb_keys
            ),
            existing_media={"photo": [], "audio": [], "video": []},
            stale_keys=unknown,
        ), 422
    db.commit()
    return redirect(url_for("sessions.detail", session_id=session_row.id))


@sessions_bp.get("/sessions/<session_id>")
def detail(session_id: str):
    s = _session_or_404(session_id)
    enabled_dims = enabled_rating_dimensions()
    enabled_ids = [d.id for d in enabled_dims]
    current, archived = split_ratings(s.ratings_json, enabled_ids)
    overall = compute_overall(s.ratings_json, enabled_dims)
    # Build (dim, value) tuples for the template so it can render label,
    # value, weight, star fill in one pass.
    dim_by_id = {d.id: d for d in enabled_dims}
    current_with_dims = [(dim_by_id[rid], value) for rid, value in current]
    photos = [j.media_file for j in s.media_joins if j.media_file.media_type == "photo"]
    audios = [j.media_file for j in s.media_joins if j.media_file.media_type == "audio"]
    videos = [j.media_file for j in s.media_joins if j.media_file.media_type == "video"]
    from flexlog.db.models import MediaFile
    db = get_db()
    link_thumbnails = {}
    for link in s.links:
        if link.thumbnail_media_id:
            mf = db.get(MediaFile, link.thumbnail_media_id)
            if mf is not None:
                link_thumbnails[link.id] = mf
    return render_template(
        "sessions/detail.html",
        person=s.person, session=s,
        current_ratings=current_with_dims,
        overall=overall,
        archived_ratings=archived,
        photos=photos, audios=audios, videos=videos,
        link_thumbnails=link_thumbnails,
    )


@sessions_bp.get("/sessions/<session_id>/edit")
def edit(session_id: str):
    s = _session_or_404(session_id)
    form = SessionForm(data={"session_date": s.session_date, "notes": s.notes or ""})
    enabled_ids = [d.id for d in enabled_rating_dimensions()]
    current_pairs, _archived = split_ratings(s.ratings_json, enabled_ids)
    existing_ratings = dict(current_pairs)
    db = get_db()
    existing_links = []
    for li in s.links:
        thumb_key = ""
        thumb_url = ""
        if li.thumbnail_media_id:
            mf = db.get(MediaFile, li.thumbnail_media_id)
            if mf is not None and mf.media_type == "photo":
                thumb_key = mf.file_key
                thumb_url = url_for("media.serve", file_key=mf.file_key)
        existing_links.append({
            "url": li.url, "thumb_key": thumb_key, "thumb_url": thumb_url,
        })
    grouped: dict[str, list] = {"photo": [], "audio": [], "video": []}
    for j in s.media_joins:
        grouped[j.media_file.media_type].append(j.media_file)
    return render_template(
        "sessions/edit.html",
        form=form,
        person=s.person,
        session=s,
        rating_dimensions=enabled_rating_dimensions(),
        existing_ratings=existing_ratings,
        existing_links=existing_links,
        existing_media=grouped,
    )


@sessions_bp.post("/sessions/<session_id>")
def update(session_id: str):
    s = _session_or_404(session_id)
    form = SessionForm()
    rating_dimensions = enabled_rating_dimensions()
    submitted_link_urls = _parse_link_urls_from_request()
    submitted_link_thumb_keys = _parse_link_thumb_keys_from_request()
    if not form.validate_on_submit():
        grouped: dict[str, list] = {"photo": [], "audio": [], "video": []}
        for j in s.media_joins:
            grouped[j.media_file.media_type].append(j.media_file)
        return render_template(
            "sessions/edit.html",
            form=form,
            person=s.person,
            session=s,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_ratings_from_request(),
            existing_links=_build_existing_links_for_template(
                submitted_link_urls, submitted_link_thumb_keys
            ),
            existing_media=grouped,
        ), 400
    db = get_db()
    try:
        update_session(
            db, session_id,
            session_date=form.session_date.data,
            ratings=_parse_ratings_from_request(),
            notes=(form.notes.data or None),
            link_urls=submitted_link_urls,
            link_thumb_keys=submitted_link_thumb_keys,
        )
        unlink_media_from_session(db, session_id, _parse_unlinked_keys_from_request())
        _created, unknown = link_media_to_session(
            db, session_id, _parse_keys_from_request()
        )
    except SessionNotFoundError:
        abort(404)
    if unknown:
        db.rollback()
        grouped: dict[str, list] = {"photo": [], "audio": [], "video": []}
        for j in s.media_joins:
            grouped[j.media_file.media_type].append(j.media_file)
        flash(
            "Some uploaded files are no longer available "
            f"({len(unknown)} stale key{'s' if len(unknown) != 1 else ''}). "
            "Remove the marked rows and try again.",
            "error",
        )
        return render_template(
            "sessions/edit.html",
            form=form,
            person=s.person,
            session=s,
            rating_dimensions=rating_dimensions,
            existing_ratings=_parse_ratings_from_request(),
            existing_links=_build_existing_links_for_template(
                submitted_link_urls, submitted_link_thumb_keys
            ),
            existing_media=grouped,
            stale_keys=unknown,
        ), 422
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
