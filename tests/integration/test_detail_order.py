"""Detail page sections render in the new order and the audio template
has no download link."""
from __future__ import annotations

import io

from tests.integration.test_session_async_upload import JPEG_1x1


def test_detail_section_order(authed_client, person, db_session):
    from flexlog.services.sessions import create_session, link_media_to_session
    from flexlog.services.media import upload_to_media_file
    from werkzeug.datastructures import FileStorage

    s = create_session(
        db_session, person_id=person.id, session_date="2026-01-01",
        ratings={"energy": 3}, notes="my notes here",
        link_urls=["https://example.com/x"],
    )
    db_session.flush()
    photo = upload_to_media_file(
        db_session,
        FileStorage(stream=io.BytesIO(JPEG_1x1), filename="t.jpg", content_type="image/jpeg"),
    )
    link_media_to_session(db_session, s.id, {"photo": [photo.file_key], "audio": [], "video": []})
    db_session.commit()

    body = authed_client.get(f"/sessions/{s.id}").get_data(as_text=True)

    # Section anchors (class names we ship in the template)
    i_links = body.find("links-display")
    i_ratings = body.find("ratings-display")
    i_notes = body.find("notes-display")
    i_audio = body.find("audios-section")
    i_photos = body.find("photos-section")
    i_videos = body.find("videos-section")

    # Required sections always present; media sections only when present.
    assert i_links >= 0 and i_ratings >= 0 and i_notes >= 0
    assert i_photos >= 0  # we attached a photo
    # Order check (use a sentinel for sections that may be -1):
    SENT = 1 << 30
    order = [
        i_links,
        i_ratings,
        i_notes,
        i_audio if i_audio >= 0 else SENT,
        i_photos,
        i_videos if i_videos >= 0 else SENT,
    ]
    # Filter out SENT entries before checking ascending order
    real = [v for v in order if v != SENT]
    assert real == sorted(real)


def test_audio_template_has_no_download_link():
    from pathlib import Path
    body = Path("flexlog/templates/_partials/media_audio.html").read_text()
    assert "audio-download" not in body
    assert 'class="audio-download"' not in body
