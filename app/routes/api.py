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


@api_bp.route("/calibration/apply", methods=["POST"])
def calibration_apply():
    """Apply calculated GAIN and OFFSET to ESP32 NVS, preserving current 4 resistors."""
    from app.services.esp32_client import get_device_client
    from app.services.calibration_history_service import get_history_service
    from flask import current_app

    calib_service = get_calibration_service()
    state = calib_service.get_state()

    if state.get("status") != "completed" or not state.get("results"):
        return jsonify({"error": "La calibración no está completa o no tiene resultados válidos"}), 400

    client = get_device_client()
    if not client.is_connected():
        return jsonify({"error": "ESP32 no está conectado"}), 400

    results = state["results"]
    gain = float(results["gain"])
    offset_kpa = float(results["offset"])

    try:
        verified_calib = client.apply_calculated_calibration(gain, offset_kpa)
    except Exception as err:
        return jsonify({"error": str(err)}), 400

    # NVS write succeeded! Now attempt SQLite history save cleanly without failing NVS status
    firmware_version = None
    try:
        device_info = client.get_device_info()
        firmware_version = device_info.get("firmware_version")
    except Exception:
        pass

    history_saved = False
    history_error = None
    try:
        db_path = current_app.config.get("CALIBRATION_DB_PATH")
        history_svc = get_history_service(db_path=db_path)
        history_svc.save_session(state, firmware_version=firmware_version)
        history_saved = True
    except Exception as h_err:
        current_app.logger.error(f"Failed to save calibration history: {h_err}", exc_info=True)
        history_saved = False
        history_error = str(h_err)

    resp: dict[str, Any] = {
        "status": "success",
        "message": "Calibración aplicada y verificada en NVS",
        "calibration": verified_calib,
        "history_saved": history_saved,
    }
    if history_error:
        resp["history_error"] = history_error

    return jsonify(resp)


@api_bp.route("/calibration/history", methods=["GET"])
def calibration_history_list():
    """List all saved calibration sessions ordered by saved_at DESC (excluding raw samples)."""
    from app.services.calibration_history_service import get_history_service
    from flask import current_app

    db_path = current_app.config.get("CALIBRATION_DB_PATH")
    history_svc = get_history_service(db_path=db_path)
    sessions = history_svc.list_sessions()
    return jsonify(sessions)


@api_bp.route("/calibration/history/<session_id>", methods=["GET"])
def calibration_history_detail(session_id: str):
    """Return detailed session information including all 7 points, raw samples and timestamps."""
    from app.services.calibration_history_service import get_history_service
    from flask import current_app

    db_path = current_app.config.get("CALIBRATION_DB_PATH")
    history_svc = get_history_service(db_path=db_path)
    detail = history_svc.get_session_detail(session_id)
    if detail is None:
        return jsonify({"error": f"Sesión de calibración '{session_id}' no encontrada"}), 404
    return jsonify(detail)


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


@api_bp.route("/config/verify-nvs", methods=["POST"])
def config_verify_nvs():
    """Perform safe NVS write & readback verification on ESP32 without altering active parameters."""
    from app.services.esp32_client import get_device_client
    client = get_device_client()
    if not client.is_connected():
        return jsonify({"error": "ESP32 no está conectado"}), 400

    try:
        verified_calib = client.verify_nvs_write()
        return jsonify({
            "status": "success",
            "message": "Escritura en NVS verificada correctamente",
            "calibration": verified_calib,
        })
    except Exception as err:
        return jsonify({"error": str(err)}), 400

