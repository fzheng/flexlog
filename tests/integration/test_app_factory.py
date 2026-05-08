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


def test_configure_logging_attaches_handler_to_named_logger(tmp_data_dir):
    """create_app() should attach a handler to the 'flexlog' logger."""
    import logging

    from flexlog.app import LOGGER_NAME

    logger = logging.getLogger(LOGGER_NAME)
    # Drop any handlers that previous tests left behind so we observe the
    # attach-once behavior cleanly.
    logger.handlers.clear()

    create_app()
    assert len(logger.handlers) == 1


def test_configure_logging_is_idempotent(tmp_data_dir):
    """Calling create_app() twice must not double-attach the handler."""
    import logging

    from flexlog.app import LOGGER_NAME

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()

    create_app()
    handlers_after_first = len(logger.handlers)
    create_app()
    handlers_after_second = len(logger.handlers)
    assert handlers_after_first == 1
    assert handlers_after_second == 1


def test_create_app_writes_secret_key_on_first_run(tmp_data_dir):
    """After create_app() the .secret_key file must exist with mode 0600."""
    import stat

    create_app()
    key_file = tmp_data_dir / ".secret_key"
    assert key_file.exists()
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600


def test_create_app_creates_database_with_tables(tmp_data_dir):
    from sqlalchemy import inspect

    app = create_app()
    engine = app.config["FLEXLOG_DB_ENGINE"]
    names = set(inspect(engine).get_table_names())
    assert {"person", "tag", "person_tag"} <= names


def test_create_app_attaches_session_factory(tmp_data_dir):
    app = create_app()
    factory = app.config["FLEXLOG_DB_SESSION_FACTORY"]
    assert callable(factory)
    with factory() as s:
        from sqlalchemy import text

        assert s.execute(text("SELECT 1")).scalar() == 1


def test_csrf_is_enabled_in_production_default(tmp_data_dir):
    """create_app() must set WTF_CSRF_ENABLED = True by default.

    The `app` fixture overrides this for testing convenience; this test
    constructs the app directly to verify the default.
    """
    app = create_app()
    assert app.config["WTF_CSRF_ENABLED"] is True


def test_get_db_returns_same_session_within_request(app):
    """get_db() must memoize within a single app context."""
    from flexlog.db import close_db, get_db

    with app.app_context():
        a = get_db()
        b = get_db()
        assert a is b
        close_db()
