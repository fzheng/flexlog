"""flexlog blueprints + Flask wiring helpers."""

from __future__ import annotations

from flask import Flask

from flexlog.web.auth_bp import auth_bp
from flexlog.web.dashboard_bp import dashboard_bp
from flexlog.web.landing_bp import landing_bp
from flexlog.web.library_bp import library_bp
from flexlog.web.media_bp import media_bp
from flexlog.web.people_bp import people_bp
from flexlog.web.sessions_bp import sessions_bp
from flexlog.web.settings_bp import settings_bp
from flexlog.web.setup_bp import setup_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(landing_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(settings_bp)
