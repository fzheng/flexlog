"""Status bar surfaces last_backup_at when running with S3 backend.
Hidden when running with local storage."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_last_backup():
    from flexlog.services import db_backup
    db_backup._LAST_SUCCESS["at"] = None
    yield
    db_backup._LAST_SUCCESS["at"] = None


def test_status_bar_hides_backup_when_local(authed_client):
    """In local-storage mode (the test fixture default), the status
    bar must NOT show 'Backup: …' — there's no S3 backup running."""
    body = authed_client.get("/dashboard").get_data(as_text=True)
    assert "Backup:" not in body


def test_status_bar_shows_recent_backup_when_value_set(
    authed_client, monkeypatch
):
    """Monkey-patch the last-backup timestamp and assert the status
    bar renders a 'Backup: <ago>' chip."""
    import datetime
    fixed = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)
    monkeypatch.setattr(
        "flexlog.services.db_backup.last_successful_backup_at",
        lambda: fixed,
    )
    body = authed_client.get("/dashboard").get_data(as_text=True)
    assert "Backup:" in body
