"""People CRUD routes."""

from __future__ import annotations

import base64
import io
import re

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.datastructures import FileStorage

from flexlog.db import get_db
from flexlog.services.media import upload_to_media_file
from flexlog.services.people import (
    PersonNotFoundError,
    create_person,
    delete_person,
    get_person,
    update_person,
)
from flexlog.services.sessions import list_sessions_for_person
from flexlog.web.forms import PersonForm

_DATAURL_RE = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,(.+)$")


def _avatar_from_dataurl(dataurl: str) -> FileStorage | None:
    """Decode a `data:image/jpeg;base64,...` string into a FileStorage we can
    feed to `services.media.upload_to_media_file`. Returns None if the input
    is empty/invalid (caller treats as 'no change').
    """
    s = (dataurl or "").strip()
    if not s:
        return None
    m = _DATAURL_RE.match(s)
    if not m:
        return None
    mime = m.group(1)
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception:
        return None
    if not raw:
        return None
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    return FileStorage(
        stream=io.BytesIO(raw),
        filename=f"avatar.{ext}",
        content_type=mime,
    )

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
    avatar_media_id = None
    fs = _avatar_from_dataurl(form.avatar_blob.data or "")
    if fs is not None:
        mf = upload_to_media_file(db, fs)
        avatar_media_id = mf.id
    person = create_person(
        db,
        alias=form.alias.data,
        tag_input=form.tags.data or "",
        avatar_media_id=avatar_media_id,
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
    # Decide what to do with the avatar:
    #   * non-empty avatar_blob → upload + set new id
    #   * clear_avatar checked  → set None
    #   * neither                → leave unchanged (sentinel)
    avatar_kw: dict = {}
    fs = _avatar_from_dataurl(form.avatar_blob.data or "")
    if fs is not None:
        mf = upload_to_media_file(db, fs)
        avatar_kw["avatar_media_id"] = mf.id
    elif form.clear_avatar.data:
        avatar_kw["avatar_media_id"] = None
    try:
        update_person(
            db, person_id,
            alias=form.alias.data,
            tag_input=form.tags.data or "",
            **avatar_kw,
        )
    except PersonNotFoundError:
        abort(404)
    db.commit()
    return redirect(url_for("people.detail", person_id=person_id))


@people_bp.get("/<person_id>")
def detail(person_id: str):
    person = _person_or_404(person_id)
    sessions = list_sessions_for_person(get_db(), person_id)
    return render_template("people/detail.html", person=person, sessions=sessions)


@people_bp.post("/<person_id>/delete")
def destroy(person_id: str):
    person = _person_or_404(person_id)
    confirm = (request.form.get("confirm_alias") or "").strip()
    if confirm != person.alias:
        flash("Alias did not match — person not deleted.", "error")
        sessions = list_sessions_for_person(get_db(), person_id)
        return render_template("people/detail.html", person=person, sessions=sessions, delete_error=True), 400
    db = get_db()
    try:
        delete_person(db, person_id)
    except PersonNotFoundError:
        abort(404)
    db.commit()
    flash(f"Deleted {person.alias}.", "success")
    return redirect(url_for("home.home"))
