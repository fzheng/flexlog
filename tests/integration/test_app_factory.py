from pathlib import Path

import pytest

from flexlog.app import create_app
from flexlog.config_loader import ConfigError
from flexlog.paths import DataDirError


def test_create_app_happy_path(tmp_data_dir):
    app = create_app()
    assert app.name == "flexlog"
    # Config is stashed
    cfg = app.config["FLEXLOG"]
    assert cfg.app.name == "Interview Log"
    # Layout was ensured
    assert (tmp_data_dir / "data").is_dir()
    assert (tmp_data_dir / "uploads").is_dir()
    assert (tmp_data_dir / "uploads" / ".tmp").is_dir()


def test_create_app_bootstraps_default_config_when_missing(tmp_data_dir_no_config):
    app = create_app()
    cfg_file = tmp_data_dir_no_config / "config.json"
    assert cfg_file.exists()
    assert app.config["FLEXLOG"].app.name == "Interview Log"


def test_create_app_unset_data_dir_raises(monkeypatch):
    monkeypatch.delenv("FLEXLOG_DATA_DIR", raising=False)
    with pytest.raises(DataDirError):
        create_app()


def test_create_app_relative_data_dir_raises(monkeypatch):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", "relative/path")
    with pytest.raises(DataDirError, match="absolute"):
        create_app()


def test_create_app_nonexistent_data_dir_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("FLEXLOG_DATA_DIR", str(tmp_path / "nope"))
    with pytest.raises(DataDirError, match="does not exist"):
        create_app()


def test_create_app_malformed_config_raises(tmp_data_dir_no_config):
    (tmp_data_dir_no_config / "config.json").write_text("{ not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        create_app()


def test_create_app_csp_friendly_no_debug_by_default(tmp_data_dir):
    app = create_app()
    assert app.debug is False


def test_create_app_debug_enabled_via_env(monkeypatch, tmp_data_dir):
    monkeypatch.setenv("FLEXLOG_DEBUG", "1")
    app = create_app()
    assert app.debug is True
