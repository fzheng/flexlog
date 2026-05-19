"""Verify tests can never touch the user's real $FLEXLOG_DATA_DIR.

The conftest.py session-autouse `_isolate_from_prod_data_dir` fixture
pops `FLEXLOG_DATA_DIR` from `os.environ` at session start and restores
it at session end. Plus a per-test autouse `_no_prod_env_leak` fixture
asserts no test left the env pointing at a real data dir.

These tests check the safety net itself works. If they fail, the
mechanism that keeps the test suite from accidentally writing into
prod is broken — investigate before continuing.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_flexlog_data_dir_not_set_at_session_start():
    """By the time individual tests run, FLEXLOG_DATA_DIR should NOT be
    in os.environ unless a monkeypatch-using fixture put it there.
    The session-autouse fixture in conftest.py pops it at session start.
    """
    # If a fixture earlier in this test's chain set it, that's fine —
    # but for THIS test (no fixtures), it must be unset.
    assert "FLEXLOG_DATA_DIR" not in os.environ, (
        f"FLEXLOG_DATA_DIR={os.environ['FLEXLOG_DATA_DIR']!r} leaked "
        f"into a test that didn't request a fixture. The session "
        f"safety net in conftest.py:_isolate_from_prod_data_dir "
        f"should have stripped it."
    )


def test_data_dir_call_without_fixture_raises():
    """If a hypothetical test calls flexlog.paths.data_dir() without
    monkeypatching the env, it must raise DataDirError — never silently
    return a valid path. This is the runtime check that backs up the
    conftest safety net."""
    from flexlog.paths import DataDirError, data_dir
    # No monkeypatch — env is bare per the session fixture.
    with pytest.raises(DataDirError):
        data_dir()


def test_monkeypatch_setenv_works_normally(monkeypatch, tmp_path):
    """Sanity: the safety net doesn't interfere with the normal pattern
    fixtures use (`monkeypatch.setenv`). After setenv, data_dir()
    returns the tmp path."""
    from flexlog.paths import data_dir
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path))
    assert data_dir() == tmp_path


def test_no_test_writes_to_user_real_data_dir():
    """Defense-in-depth check: search the user's most likely real data
    dir locations and verify nothing test-shaped lives in them after
    the suite has run. Skips silently if no real dir is present (the
    common case in CI / fresh clones)."""
    import time

    # The Makefile default
    candidates = [
        Path.cwd() / "flexlog-data",
        Path.home() / "flexlog-data",
    ]
    suspicious_artifacts = []
    now = time.time()
    for candidate in candidates:
        if not candidate.exists():
            continue
        # Don't touch the candidate; just inspect mtimes. If a test
        # accidentally wrote here, the data dir's mtime would be
        # within the last few seconds (this suite's runtime).
        try:
            for sub in ("data", "uploads", "config.json", "kdf_params.json"):
                p = candidate / sub
                if p.exists() and (now - p.stat().st_mtime) < 60:
                    suspicious_artifacts.append(
                        f"  {p}: mtime within the last 60s "
                        f"({int(now - p.stat().st_mtime)}s ago)"
                    )
        except OSError:
            continue
    assert not suspicious_artifacts, (
        "A test wrote into the user's real data dir within the last "
        "60s! The session-isolation fixture in conftest.py is not "
        "working. Affected paths:\n" + "\n".join(suspicious_artifacts)
    )
