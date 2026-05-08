"""flexlog blueprints + Flask wiring helpers."""

from __future__ import annotations

from flask import Flask

from flexlog.web.home_bp import home_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(home_bp)
