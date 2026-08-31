"""Monitor blueprint — Phase 2.

Serves the /monitor page only. Telemetry data is fetched by the browser
from GET /api/telemetry (see app/routes/api.py).
"""
from flask import Blueprint, render_template

monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")


@monitor_bp.route("/")
def index():
    """Oxygen sensor live monitor page."""
    return render_template("monitor.html")
