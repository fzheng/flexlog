"""Unit tests for flexlog.app module-level helpers."""

from __future__ import annotations

import os
import time


def test_tmp_sweep_cutoff_is_24_hours(monkeypatch, tmp_path):
    """tmp-uploads sweep must use a 24h cutoff. A long upload on slow
    disk shouldn't race a 1h sweep across an app restart."""
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    from flexlog import paths
    tmp_dir = paths.tmp_uploads_dir()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Two stale files: one older than 24h, one older than 1h but younger than 24h.
    old = tmp_dir / "old.part"
    medium = tmp_dir / "medium.part"
    old.write_bytes(b"x")
    medium.write_bytes(b"y")
    now = time.time()
    os.utime(old, (now - 90000, now - 90000))      # 25h old
    os.utime(medium, (now - 7200, now - 7200))     # 2h old

    from flexlog.app import _sweep_tmp_uploads  # the function the cutoff lives in
    _sweep_tmp_uploads()

    # 25h file gone, 2h file survives (within new 24h window)
    assert not old.exists()
    assert medium.exists()
