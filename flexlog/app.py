"""Flask application factory for flexlog."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask

from flexlog import paths
from flexlog.config_loader import Config, load_or_bootstrap
from flexlog.web import register_blueprints
from flexlog.web.filters import build_labels_context, ui_filter


def create_app() -> Flask:
    """Build and return the configured Flask app.

    Reads FLEXLOG_DATA_DIR (required), loads/bootstraps config.json, and
    raises (DataDirError or ConfigError) if anything is wrong. No fallback
    values — startup failures are loud and explicit.
    """
    _configure_logging()

    # 1. Validate data dir + create child layout
    data_dir = paths.data_dir()  # raises DataDirError on failure
    paths.ensure_layout()

    # 2. Load (or bootstrap) config.json
    config: Config = load_or_bootstrap(paths.config_path())

    # 3. Build the Flask app
    app = Flask(
        "flexlog",
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["FLEXLOG"] = config
    app.config["FLEXLOG_DATA_DIR"] = str(data_dir)
    app.debug = os.environ.get("FLEXLOG_DEBUG", "") == "1"

    # 4. Wire up filters + context processor
    app.jinja_env.filters["ui"] = lambda key: ui_filter(key)

    @app.context_processor
    def _inject_labels() -> dict[str, object]:
        return {"labels": build_labels_context(config)}

    # 5. Register blueprints
    register_blueprints(app)

    return app


LOGGER_NAME = "flexlog"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _configure_logging() -> None:
    """Attach a stderr handler at INFO to the named flexlog logger.

    Idempotent — only attaches a handler once per process.
    """
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
