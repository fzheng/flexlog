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


# ------------------------------------------------ _install_one (write path)


def test_install_one_writes_plist_to_correct_location(monkeypatch, tmp_path):
    """_install_one writes <name>.plist to LAUNCH_AGENTS_DIR and runs
    launchctl bootstrap. Monkey-patches LAUNCH_AGENTS_DIR to tmp_path so
    we don't touch the real ~/Library/LaunchAgents."""
    from unittest.mock import MagicMock

    import scripts.install_launch_agents as inst

    monkeypatch.setattr(inst, "LAUNCH_AGENTS_DIR", tmp_path / "LaunchAgents")
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stderr="", stdout=""))
    monkeypatch.setattr(inst.subprocess, "run", fake_run)

    rendered = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        '<plist version="1.0"><dict>'
        '<key>Label</key><string>com.flexlog.app</string>'
        '<key>RunAtLoad</key><true/>'
        '</dict></plist>'
    )
    dst = inst._install_one("com.flexlog.app", rendered, dry_run=False)

    assert dst == tmp_path / "LaunchAgents" / "com.flexlog.app.plist"
    assert dst.exists()
    assert dst.read_text() == rendered
    # mode 0o644 per macOS norm
    assert oct(dst.stat().st_mode & 0o777) == "0o644"

    # bootout + bootstrap both invoked (bootout first for idempotency)
    calls = [c.args[0] for c in fake_run.call_args_list]
    assert calls[0][:3] == ["launchctl", "bootout", f"gui/{inst.os.getuid()}"]
    assert calls[1][:3] == ["launchctl", "bootstrap", f"gui/{inst.os.getuid()}"]


def test_install_one_raises_on_invalid_plist(monkeypatch, tmp_path):
    """If rendered content is not a valid plist, _install_one raises
    BEFORE writing to disk — we never leave garbage in ~/Library/LaunchAgents."""
    import scripts.install_launch_agents as inst

    monkeypatch.setattr(inst, "LAUNCH_AGENTS_DIR", tmp_path / "LaunchAgents")

    import pytest as _pytest
    with _pytest.raises(RuntimeError, match="not valid"):
        inst._install_one("com.flexlog.app", "this is not a plist", dry_run=False)

    # Nothing got written
    assert not (tmp_path / "LaunchAgents" / "com.flexlog.app.plist").exists()


def test_install_one_propagates_bootstrap_failure(monkeypatch, tmp_path):
    """A bootstrap failure (e.g., bad plist semantics that launchctl rejects)
    must raise RuntimeError with launchctl's stderr — NOT be silently swallowed."""
    from unittest.mock import MagicMock

    import scripts.install_launch_agents as inst

    monkeypatch.setattr(inst, "LAUNCH_AGENTS_DIR", tmp_path / "LaunchAgents")

    def fake_run(cmd, **kwargs):
        # Bootout succeeds (returncode 0 doesn't matter — we suppress its errors).
        # Bootstrap fails with returncode 1 + stderr.
        if "bootstrap" in cmd:
            return MagicMock(returncode=1, stderr="launchctl: bad plist", stdout="")
        return MagicMock(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(inst.subprocess, "run", fake_run)

    rendered = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        '<plist version="1.0"><dict>'
        '<key>Label</key><string>com.flexlog.app</string>'
        '</dict></plist>'
    )

    import pytest as _pytest
    with _pytest.raises(RuntimeError, match="bootstrap.*failed"):
        inst._install_one("com.flexlog.app", rendered, dry_run=False)


def test_install_one_dry_run_writes_nothing(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    import scripts.install_launch_agents as inst

    monkeypatch.setattr(inst, "LAUNCH_AGENTS_DIR", tmp_path / "LaunchAgents")
    fake_run = MagicMock()
    monkeypatch.setattr(inst.subprocess, "run", fake_run)

    rendered = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        '<plist version="1.0"><dict>'
        '<key>Label</key><string>com.flexlog.app</string>'
        '</dict></plist>'
    )
    inst._install_one("com.flexlog.app", rendered, dry_run=True)

    assert not (tmp_path / "LaunchAgents" / "com.flexlog.app.plist").exists()
    fake_run.assert_not_called()
