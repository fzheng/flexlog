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
from flexlog.services.sessions import list_sessions_for_person
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
