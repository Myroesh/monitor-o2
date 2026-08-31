"""Configuration blueprint."""
from flask import Blueprint, render_template

configuration_bp = Blueprint("configuration", __name__, url_prefix="/configuration")


@configuration_bp.route("/")
def index():
    """Application configuration page."""
    return render_template("configuration.html")
