"""Application factory."""
from flask import Flask, redirect, url_for

from app.routes.monitor import monitor_bp
from app.routes.calibration import calibration_bp
from app.routes.configuration import configuration_bp
from app.routes.api import api_bp


def create_app(config: dict | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Default configuration
    app.config.setdefault("SECRET_KEY", "dev-secret-key-change-in-production")
    app.config.setdefault("TESTING", False)

    # Override with any config passed in (useful for tests)
    if config:
        app.config.update(config)

    # Register blueprints
    app.register_blueprint(monitor_bp)
    app.register_blueprint(calibration_bp)
    app.register_blueprint(configuration_bp)
    app.register_blueprint(api_bp)

    # Root redirect
    @app.route("/")
    def index():
        return redirect(url_for("monitor.index"))

    return app
