"""API blueprint — Phase 2 & Phase 3.

Exposes the public REST API under /api. This prefix is independent of
any page blueprint so the contract stays stable as the UI evolves.
"""
from flask import Blueprint, jsonify, request

from app.services.telemetry_service import get_service
from app.services.calibration_service import get_calibration_service

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ── Telemetry API ──────────────────────────────────────────────────────────

@api_bp.route("/telemetry")
def telemetry():
    """Return a fresh telemetry sample as JSON."""
    service = get_service()
    sample = service.tick()
    history = service.get_history()
    return jsonify({"latest": sample, "history": history})


# ── Calibration API ────────────────────────────────────────────────────────

@api_bp.route("/calibration/state", methods=["GET"])
def calibration_state():
    """Return current calibration session state."""
    service = get_calibration_service()
    return jsonify(service.get_state())


@api_bp.route("/calibration/start", methods=["POST"])
def calibration_start():
    """Start or reset a calibration session."""
    service = get_calibration_service()
    return jsonify(service.reset_session())


@api_bp.route("/calibration/update-point", methods=["POST"])
def calibration_update_point():
    """Update observed real pressure for a step."""
    data = request.get_json() or {}
    step_index = int(data.get("step_index", 0))
    observed_mmhg = float(data.get("observed_mmhg", 0.0))

    service = get_calibration_service()
    try:
        updated_state = service.update_observed_pressure(step_index, observed_mmhg)
        return jsonify(updated_state)
    except IndexError as err:
        return jsonify({"error": str(err)}), 400


@api_bp.route("/calibration/measure", methods=["POST"])
def calibration_measure():
    """Start sample capture for a step over a target time window."""
    data = request.get_json() or {}
    step_index = int(data.get("step_index", 0))
    duration_s = float(data.get("target_duration_s", 4.0))
    min_samples = int(data.get("min_samples", 10))

    service = get_calibration_service()
    try:
        updated_state = service.start_measuring(step_index, target_duration_s=duration_s, min_samples=min_samples)
        return jsonify(updated_state)
    except IndexError as err:
        return jsonify({"error": str(err)}), 400


@api_bp.route("/calibration/next", methods=["POST"])
def calibration_next():
    """Advance to next calibration step."""
    service = get_calibration_service()
    return jsonify(service.next_step())


@api_bp.route("/calibration/prev", methods=["POST"])
def calibration_prev():
    """Go back to previous calibration step."""
    service = get_calibration_service()
    return jsonify(service.previous_step())


@api_bp.route("/calibration/repeat", methods=["POST"])
def calibration_repeat():
    """Reset samples for a specific step to measure again."""
    data = request.get_json() or {}
    step_index = int(data.get("step_index", 0))

    service = get_calibration_service()
    try:
        updated_state = service.repeat_step(step_index)
        return jsonify(updated_state)
    except IndexError as err:
        return jsonify({"error": str(err)}), 400


@api_bp.route("/calibration/calculate", methods=["POST"])
def calibration_calculate():
    """Explicitly trigger linear regression calculation."""
    service = get_calibration_service()
    return jsonify(service.calculate_results())


# ── Configuration API ──────────────────────────────────────────────────────

@api_bp.route("/config", methods=["GET"])
def config_get():
    """Return full device status, hardware parameters, and calibration config."""
    from app.services.esp32_client import get_device_client
    client = get_device_client()
    return jsonify(client.get_device_info())


@api_bp.route("/config", methods=["POST"])
def config_update():
    """Validate and update simulated device configuration in memory."""
    from app.services.esp32_client import get_device_client
    data = request.get_json() or {}
    client = get_device_client()
    try:
        updated_info = client.update_config(data)
        return jsonify(updated_info)
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

