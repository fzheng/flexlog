"""flexlog blueprints + Flask wiring helpers."""

from __future__ import annotations

from flask import Flask

from flexlog.web.dashboard_bp import dashboard_bp
from flexlog.web.people_bp import people_bp
from flexlog.web.sessions_bp import sessions_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(sessions_bp)
