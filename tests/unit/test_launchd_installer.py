"""Tests for the launchd plist template installer.

The installer is pure templating + filesystem I/O; we test the rendering
logic directly without touching launchctl or the real LaunchAgents dir."""
from __future__ import annotations

import plistlib
from pathlib import Path

import pytest


@pytest.fixture
def repo_root():
    """The flexlog repo root (where this test file lives in a subdir)."""
    return Path(__file__).resolve().parent.parent.parent


def test_render_substitutes_all_placeholders(repo_root, tmp_path):
    """Every {{PLACEHOLDER}} in the template must be substituted; the
    rendered output must contain no curly-brace placeholders."""
    from scripts.install_launch_agents import render_template

    template = repo_root / "scripts/launchd-templates/com.flexlog.app.plist.template"
    rendered = render_template(
        template,
        FLEXLOG_REPO_DIR="/Users/test/Work/flexlog",
        FLEXLOG_DATA_DIR="/Users/test/Library/Application Support/flexlog",
        FLEXLOG_LOG_DIR="/Users/test/Library/Logs/flexlog",
    )
    assert "{{" not in rendered, f"unrendered placeholder in: {rendered}"
    assert "}}" not in rendered


def test_render_app_plist_is_valid_xml_plist(repo_root):
    """Rendered output must be parseable as a macOS plist."""
    from scripts.install_launch_agents import render_template

    template = repo_root / "scripts/launchd-templates/com.flexlog.app.plist.template"
    rendered = render_template(
        template,
        FLEXLOG_REPO_DIR="/Users/test/Work/flexlog",
        FLEXLOG_DATA_DIR="/Users/test/Library/Application Support/flexlog",
        FLEXLOG_LOG_DIR="/Users/test/Library/Logs/flexlog",
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["Label"] == "com.flexlog.app"
    assert parsed["RunAtLoad"] is True
    assert parsed["KeepAlive"] is True
    assert "127.0.0.1:5050" in parsed["ProgramArguments"]
    assert parsed["EnvironmentVariables"]["FLEXLOG_DATA_DIR"] == \
        "/Users/test/Library/Application Support/flexlog"
    assert parsed["EnvironmentVariables"]["FLEXLOG_STORAGE_BACKEND"] == "local"
    assert parsed["EnvironmentVariables"]["FLEXLOG_BEHIND_TLS"] == "1"


def test_render_backup_plist_is_valid_and_15min_interval(repo_root):
    from scripts.install_launch_agents import render_template

    template = repo_root / "scripts/launchd-templates/com.flexlog.backup.plist.template"
    rendered = render_template(
        template,
        FLEXLOG_REPO_DIR="/Users/test/Work/flexlog",
        FLEXLOG_DATA_DIR="/Users/test/Library/Application Support/flexlog",
        FLEXLOG_LOG_DIR="/Users/test/Library/Logs/flexlog",
        HEALTHCHECK_URL="https://hc-ping.com/abc-123",
        RCLONE_REMOTE="railway-backup:flexlog-home-backup",
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["Label"] == "com.flexlog.backup"
    assert parsed["StartInterval"] == 900  # 15 min
    assert parsed["EnvironmentVariables"]["HEALTHCHECK_URL"] == \
        "https://hc-ping.com/abc-123"
    assert parsed["EnvironmentVariables"]["RCLONE_REMOTE"] == \
        "railway-backup:flexlog-home-backup"


def test_render_prune_plist_runs_daily_at_4am(repo_root):
    from scripts.install_launch_agents import render_template

    template = repo_root / "scripts/launchd-templates/com.flexlog.backup-prune.plist.template"
    rendered = render_template(
        template,
        FLEXLOG_REPO_DIR="/Users/test/Work/flexlog",
        FLEXLOG_LOG_DIR="/Users/test/Library/Logs/flexlog",
        RCLONE_REMOTE="railway-backup:flexlog-home-backup",
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["Label"] == "com.flexlog.backup-prune"
    assert parsed["StartCalendarInterval"]["Hour"] == 4
    assert parsed["StartCalendarInterval"]["Minute"] == 0


def test_render_raises_on_missing_placeholder(repo_root):
    """If the caller forgets to pass a required substitution, we want a
    clear error — not a silently-leftover {{...}} in the rendered file."""
    from scripts.install_launch_agents import render_template

    template = repo_root / "scripts/launchd-templates/com.flexlog.app.plist.template"
    with pytest.raises(KeyError) as exc:
        render_template(
            template,
            FLEXLOG_REPO_DIR="/x",
            # missing FLEXLOG_DATA_DIR and FLEXLOG_LOG_DIR on purpose
        )
    msg = str(exc.value)
    assert "FLEXLOG_DATA_DIR" in msg or "FLEXLOG_LOG_DIR" in msg


def test_render_handles_paths_with_spaces(repo_root):
    """macOS standard path 'Library/Application Support' contains a space.
    The rendered plist's XML must escape correctly and parse back to the
    same string."""
    from scripts.install_launch_agents import render_template

    template = repo_root / "scripts/launchd-templates/com.flexlog.app.plist.template"
    path_with_space = "/Users/test/Library/Application Support/flexlog"
    rendered = render_template(
        template,
        FLEXLOG_REPO_DIR="/Users/test/Work/flexlog",
        FLEXLOG_DATA_DIR=path_with_space,
        FLEXLOG_LOG_DIR="/Users/test/Library/Logs/flexlog",
    )
    parsed = plistlib.loads(rendered.encode("utf-8"))
    assert parsed["EnvironmentVariables"]["FLEXLOG_DATA_DIR"] == path_with_space
