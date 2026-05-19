"""PersonForm alias validation rejects whitespace-only input.

flexlog/web/forms.py:_alias_strip_required runs after DataRequired and
rejects strings that are blank-after-strip. Covers the line where the
ValidationError is raised."""
from __future__ import annotations


def test_person_form_rejects_whitespace_only_alias(app):
    """DataRequired short-circuits before our custom validator on
    whitespace-only input — either way the form must fail."""
    from flexlog.web.forms import PersonForm
    with app.test_request_context(method="POST", data={"alias": "   ", "tags": ""}):
        form = PersonForm()
        assert not form.validate()
        assert "alias" in form.errors


def test_alias_strip_required_validator_directly():
    """Call the custom validator on a fake field to exercise the
    blank-or-whitespace branch even when DataRequired would short-
    circuit it in the full validators chain."""
    import pytest
    from wtforms.validators import ValidationError
    from flexlog.web.forms import _alias_strip_required

    class _Field:
        def __init__(self, data):
            self.data = data

    # Whitespace-only — must raise
    with pytest.raises(ValidationError, match="blank or whitespace-only"):
        _alias_strip_required(None, _Field("   "))
    # Empty string — must raise
    with pytest.raises(ValidationError, match="blank or whitespace-only"):
        _alias_strip_required(None, _Field(""))
    # Non-empty — must NOT raise
    _alias_strip_required(None, _Field("Alice"))


def test_person_form_accepts_alias_with_leading_trailing_space(app):
    """A non-whitespace-only alias (with surrounding spaces) is allowed —
    services strip on insert."""
    from flexlog.web.forms import PersonForm
    with app.test_request_context(method="POST", data={"alias": "  Alice  ", "tags": ""}):
        form = PersonForm()
        assert form.validate()
