"""End-to-end: saving a session with a link triggers a thumbnail
fetch, stores it as MediaFile, and the detail page renders it."""
from __future__ import annotations

from unittest.mock import patch


def _make_jpeg_bytes(width=200, height=150, color=(40, 90, 160)):
    import io
    from PIL import Image
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_save_with_link_creates_thumbnail(authed_client, person, db_session):
    """create_session with a link → _replace_links calls fetch_thumbnail
    → MediaFile row created → SessionLink.thumbnail_media_id set →
    detail page renders <img src="/media/...">."""
    from flexlog.services.sessions import create_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg):
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article"],
        )
        db_session.commit()

    assert len(s.links) == 1
    link = s.links[0]
    assert link.thumbnail_media_id is not None

    from flexlog.db.models import MediaFile
    mf = db_session.get(MediaFile, link.thumbnail_media_id)
    assert mf is not None
    assert mf.media_type == "photo"
    assert mf.mime_type == "image/jpeg"

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    assert "link-thumb-image" in body
    assert f"/media/{mf.file_key}" in body


def test_thumbnail_fetch_failure_does_not_block_save(authed_client, person, db_session):
    """fetch_thumbnail returns None → save still succeeds → no thumbnail."""
    from flexlog.services.sessions import create_session

    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=None):
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 3}, notes=None,
            link_urls=["https://does-not-resolve.invalid/foo"],
        )
        db_session.commit()

    assert len(s.links) == 1
    assert s.links[0].thumbnail_media_id is None

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)
    assert "https://does-not-resolve.invalid/foo" in body
    assert "link-thumb-image" not in body


def test_unchanged_url_keeps_thumbnail(authed_client, person, db_session):
    """update_session with same URL list → fetch_thumbnail NOT called again."""
    from flexlog.services.sessions import create_session, update_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg) as fetch_mock:
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article"],
        )
        db_session.commit()
        assert fetch_mock.call_count == 1
        original_thumb = s.links[0].thumbnail_media_id

        update_session(
            db_session, session_id=s.id, session_date="2026-05-18",
            ratings={"energy": 5}, notes=None,
            link_urls=["https://example.com/article"],  # same URL
        )
        db_session.commit()

    # Still exactly one fetch — second save didn't re-fetch.
    assert fetch_mock.call_count == 1
    assert s.links[0].thumbnail_media_id == original_thumb


def test_changed_url_refetches(authed_client, person, db_session):
    """update_session with a different URL → fetch_thumbnail called for the new URL."""
    from flexlog.services.sessions import create_session, update_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg) as fetch_mock:
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article-1"],
        )
        db_session.commit()
        assert fetch_mock.call_count == 1
        fetch_mock.assert_called_with("https://example.com/article-1")

        update_session(
            db_session, session_id=s.id, session_date="2026-05-18",
            ratings={"energy": 5}, notes=None,
            link_urls=["https://example.com/article-2"],  # different URL
        )
        db_session.commit()

    assert fetch_mock.call_count == 2
    fetch_mock.assert_called_with("https://example.com/article-2")
    assert s.links[0].url == "https://example.com/article-2"


def test_url_reorder_preserves_thumbnails(authed_client, person, db_session):
    """Reordering existing URLs (no URL changes) should not re-fetch."""
    from flexlog.services.sessions import create_session, update_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg) as fetch_mock:
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=[
                "https://example.com/a",
                "https://example.com/b",
            ],
        )
        db_session.commit()
        assert fetch_mock.call_count == 2

        update_session(
            db_session, session_id=s.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=[  # reversed order, same URLs
                "https://example.com/b",
                "https://example.com/a",
            ],
        )
        db_session.commit()

    assert fetch_mock.call_count == 2  # NOT 4 — reorder is free
    assert s.links[0].url == "https://example.com/b"
    assert s.links[1].url == "https://example.com/a"
    # Both still have thumbnails
    assert s.links[0].thumbnail_media_id is not None
    assert s.links[1].thumbnail_media_id is not None


def test_two_sessions_same_link_dedup(authed_client, person, db_session):
    """Two sessions linking to the same URL with identical thumbnail bytes
    share one MediaFile row (existing SHA-256 dedup)."""
    from flexlog.services.sessions import create_session

    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg):
        s1 = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/shared"],
        )
        db_session.commit()
        s2 = create_session(
            db_session, person_id=person.id, session_date="2026-05-18",
            ratings={"energy": 5}, notes=None,
            link_urls=["https://example.com/shared"],
        )
        db_session.commit()

    # Same MediaFile id reused
    assert s1.links[0].thumbnail_media_id == s2.links[0].thumbnail_media_id


def test_resave_retries_failed_thumbnail(authed_client, person, db_session):
    """First save: fetch_thumbnail fails (returns None) → link saves with
    no thumbnail. Re-save the same URL: should re-fetch (because the
    cached thumb is None) and pick up the success this time. This is the
    bug-fix path for pre-M8 links: re-saving an existing session should
    populate their thumbnails."""
    from flexlog.services.sessions import create_session, update_session

    # First save: fetch fails
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=None) as fetch_mock:
        s = create_session(
            db_session, person_id=person.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article"],
        )
        db_session.commit()
        assert fetch_mock.call_count == 1
        assert s.links[0].thumbnail_media_id is None

    # Re-save the same URL: fetch now succeeds. The fact that the
    # existing thumb is None must trigger a re-fetch.
    jpeg = _make_jpeg_bytes()
    with patch("flexlog.services.sessions.fetch_thumbnail", return_value=jpeg) as fetch_mock:
        update_session(
            db_session, session_id=s.id, session_date="2026-05-17",
            ratings={"energy": 4}, notes=None,
            link_urls=["https://example.com/article"],  # unchanged URL
        )
        db_session.commit()

    # Re-fetch happened (None thumb forced retry on save)
    assert fetch_mock.call_count == 1
    assert s.links[0].thumbnail_media_id is not None
