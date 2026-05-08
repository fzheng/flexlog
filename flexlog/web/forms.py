"""Flask-WTF forms.

Forms are intentionally thin — validation logic lives in services. The
form's job is to enforce presence and length so we don't pass garbage into
the service layer or hold absurd strings in memory.
"""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

ALIAS_MAX = 200
TAGS_MAX = 1000  # comma-separated free text


def _alias_strip_required(form, field):
    if not field.data or field.data.strip() == "":
        raise ValidationError("alias must not be blank or whitespace-only")


class PersonForm(FlaskForm):
    alias = StringField(
        "alias",
        validators=[
            DataRequired(message="alias is required"),
            _alias_strip_required,
            Length(max=ALIAS_MAX),
        ],
    )
    tags = StringField(
        "tags",
        validators=[Optional(), Length(max=TAGS_MAX)],
    )
