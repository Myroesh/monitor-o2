"""Calibration blueprint."""
from flask import Blueprint, render_template

calibration_bp = Blueprint("calibration", __name__, url_prefix="/calibration")


@calibration_bp.route("/")
def index():
    """Sensor calibration page."""
    return render_template("calibration.html")
