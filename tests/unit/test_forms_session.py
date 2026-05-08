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
