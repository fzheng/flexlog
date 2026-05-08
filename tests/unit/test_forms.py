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


def test_person_form_tags_optional_when_empty(app):
    """Empty tags must be valid — only alias is required."""
    with app.test_request_context(method="POST", data={"alias": "Alice", "tags": ""}):
        form = PersonForm()
        assert form.validate(), form.errors
