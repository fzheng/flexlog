"""Flask-WTF forms.

Forms are intentionally thin — validation logic lives in services. The
form's job is to enforce presence and length so we don't pass garbage into
the service layer or hold absurd strings in memory.
"""

from __future__ import annotations

import re

from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, Regexp, ValidationError

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
    # avatar_blob: a "data:image/jpeg;base64,..." dataURL produced by Cropper.js.
    # Length cap is 12 MiB of base64 (~9 MiB raw) — way larger than any realistic
    # avatar at 512x512 JPEG quality 0.92, but small enough to reject obvious abuse.
    avatar_blob = StringField(
        "avatar_blob",
        validators=[Optional(), Length(max=12 * 1024 * 1024)],
    )
    clear_avatar = BooleanField("clear_avatar", default=False)


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
