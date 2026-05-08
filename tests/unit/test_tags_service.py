import pytest

from flexlog.db.models import Tag
from flexlog.services.tags import (
    InvalidTagError,
    get_or_create_tag,
    list_all_tags,
    normalize_tag_input,
    slugify,
)


def test_slugify_basic():
    assert slugify("Engineering") == "engineering"


def test_slugify_collapses_punctuation_and_spaces():
    assert slugify("Senior  Engineer / SRE") == "senior-engineer-sre"


def test_slugify_strips_leading_and_trailing_dashes():
    assert slugify("---hello---") == "hello"


def test_slugify_unicode_is_lowercased():
    """Non-ASCII letters are kept (Chinese, accented) but lowercased."""
    assert slugify("Café") == "café"
    assert slugify("北京 朋友") == "北京-朋友"


def test_slugify_empty_input_raises():
    with pytest.raises(InvalidTagError, match="empty"):
        slugify("   ")


def test_slugify_only_punctuation_raises():
    with pytest.raises(InvalidTagError, match="empty"):
        slugify("---!!!")


def test_normalize_tag_input_splits_and_dedups():
    """Comma-separated user input → list of cleaned (display, slug) pairs."""
    pairs = normalize_tag_input("Engineering, friend , ENGINEERING, , Coach")
    # Order preserved on first appearance; case-insensitive dedup
    assert pairs == [
        ("Engineering", "engineering"),
        ("friend", "friend"),
        ("Coach", "coach"),
    ]


def test_normalize_tag_input_empty_returns_empty_list():
    assert normalize_tag_input("") == []
    assert normalize_tag_input("   ,  ,   ") == []


def test_normalize_tag_input_drops_invalid_silently():
    """Tokens that slugify to empty are dropped; valid tokens still pass."""
    pairs = normalize_tag_input("real, ---, valid")
    assert pairs == [("real", "real"), ("valid", "valid")]


def test_get_or_create_tag_creates_when_missing(db_session):
    tag = get_or_create_tag(db_session, "Engineering")
    db_session.commit()
    assert isinstance(tag, Tag)
    assert tag.name == "Engineering"
    assert tag.slug == "engineering"
    # Round-trip
    got = db_session.query(Tag).filter_by(slug="engineering").one()
    assert got.id == tag.id


def test_get_or_create_tag_reuses_existing(db_session):
    a = get_or_create_tag(db_session, "Engineering")
    db_session.commit()
    b = get_or_create_tag(db_session, "ENGINEERING")
    db_session.commit()
    assert a.id == b.id
    assert a.name == "Engineering"  # First-seen wins on display name


def test_get_or_create_tag_invalid_raises(db_session):
    with pytest.raises(InvalidTagError):
        get_or_create_tag(db_session, "   ")


def test_list_all_tags_orders_by_name(db_session):
    get_or_create_tag(db_session, "Friend")
    get_or_create_tag(db_session, "Coach")
    get_or_create_tag(db_session, "Engineer")
    db_session.commit()
    names = [t.name for t in list_all_tags(db_session)]
    assert names == ["Coach", "Engineer", "Friend"]


def test_list_all_tags_empty(db_session):
    assert list_all_tags(db_session) == []


def test_slugify_non_string_raises():
    with pytest.raises(InvalidTagError, match="string"):
        slugify(123)  # type: ignore[arg-type]
