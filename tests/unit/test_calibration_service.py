"""Unit tests for calibration_service — math, known datasets, time-window sample capture, and session state."""
import pytest
import time
from app import create_app
from app.services.telemetry_service import get_service
from app.services.calibration_service import (
    CalibrationService,
    MMHG_TO_KPA,
    calculate_sample_stats,
    fit_linear_regression,
    mmhg_to_kpa,
)


class TestCreateApp:
    def test_create_app_returns_flask_app(self):
        app = create_app()
        assert app is not None

    def test_testing_config(self):
        app = create_app({"TESTING": True})
        assert app.config["TESTING"] is True

    def test_blueprints_registered(self):
        app = create_app()
        blueprint_names = set(app.blueprints.keys())
        assert "monitor" in blueprint_names
        assert "calibration" in blueprint_names
        assert "configuration" in blueprint_names
        assert "api" in blueprint_names


class TestUnitConversion:
    def test_mmhg_to_kpa_exact_factor(self):
        assert mmhg_to_kpa(1.0) == 0.133322
        assert mmhg_to_kpa(100.0) == 13.3322
        assert mmhg_to_kpa(0.0) == 0.0


class TestSampleStats:
    def test_empty_samples(self):
        stats = calculate_sample_stats([])
        assert stats == {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}

    def test_single_sample_std_is_zero(self):
        stats = calculate_sample_stats([10.5])
        assert stats["mean"] == 10.5
        assert stats["std"] == 0.0
        assert stats["min"] == 10.5
        assert stats["max"] == 10.5
        assert stats["count"] == 1

    def test_known_samples(self):
        samples = [10.0, 12.0, 14.0]
        stats = calculate_sample_stats(samples)
        assert stats["mean"] == 12.0
        assert pytest.approx(stats["std"], 0.0001) == 2.0
        assert stats["min"] == 10.0
        assert stats["max"] == 14.0
        assert stats["count"] == 3


class TestLinearRegressionMath:
    def test_identity_dataset(self):
        x = [0.0, 10.0, 20.0, 30.0]
        y = [0.0, 10.0, 20.0, 30.0]
        reg = fit_linear_regression(x, y)
        assert reg["gain"] == 1.0
        assert reg["offset"] == 0.0
        assert reg["r_squared"] == 1.0
        assert reg["residuals"] == [0.0, 0.0, 0.0, 0.0]
        assert reg["max_error"] == 0.0
        assert reg["mean_absolute_error"] == 0.0

    def test_known_gain_and_offset_dataset(self):
        x = [10.0, 20.0, 30.0, 40.0]
        y = [25.0, 45.0, 65.0, 85.0]
        reg = fit_linear_regression(x, y)
        assert reg["gain"] == 2.0
        assert reg["offset"] == 5.0
        assert reg["r_squared"] == 1.0
        assert reg["max_error"] == 0.0

    def test_known_dataset_with_residuals(self):
        x = [0.0, 50.0, 100.0, 150.0, 200.0, 250.0, 300.0]
        y = [mmhg_to_kpa(val) for val in x]
        reg = fit_linear_regression(x, y)
        assert pytest.approx(reg["gain"], 0.000001) == MMHG_TO_KPA
        assert pytest.approx(reg["offset"], 0.000001) == 0.0
        assert reg["r_squared"] == 1.0


class TestCalibrationServiceSession:
    def test_initial_session_state(self):
        service = CalibrationService()
        state = service.get_state()
        assert state["current_step"] == 0
        assert state["total_steps"] == 7
        assert state["status"] == "in_progress"
        assert len(state["points"]) == 7
        assert state["results"] is None

    def test_update_observed_pressure(self):
        service = CalibrationService()
        state = service.update_observed_pressure(1, 52.5)
        pt = state["points"][1]
        assert pt["observed_mmhg"] == 52.5
        assert pytest.approx(pt["observed_kpa"], 0.0001) == 52.5 * MMHG_TO_KPA

    def test_time_window_sample_capture_completion(self):
        service = CalibrationService()
        state = service.start_measuring(0, target_duration_s=4.0, min_samples=10)
        assert state["points"][0]["status"] == "measuring"

        telemetry = get_service()
        start_ts = time.time()

        # Feed 10 samples spread over 4.5 seconds
        for i in range(10):
            t_sample = start_ts + (i * 0.5)  # 0.0s to 4.5s
            telemetry.add_sample({"ts": t_sample, "p_nominal_kpa": 100.0 + i})

        state = service.get_state()
        pt = state["points"][0]
        assert pt["status"] == "completed"
        assert pt["samples_received"] == 10
        assert pt["target_duration_seconds"] == 4.0
        assert pt["min_samples_required"] == 10
        assert pt["effective_frequency_hz"] > 0.0

    def test_insufficient_samples_timeout_error(self):
        """If time window exceeds safety timeout without reaching min_samples, point is not completed."""
        service = CalibrationService()
        service.start_measuring(0, target_duration_s=4.0, min_samples=10)

        telemetry = get_service()
        start_ts = time.time()

        # Feed only 3 samples but advance time past 16 seconds
        telemetry.add_sample({"ts": start_ts, "p_nominal_kpa": 100.0})
        telemetry.add_sample({"ts": start_ts + 8.0, "p_nominal_kpa": 101.0})
        telemetry.add_sample({"ts": start_ts + 16.0, "p_nominal_kpa": 102.0})

        state = service.get_state()
        pt = state["points"][0]
        assert pt["status"] == "insufficient_samples"
        assert pt["status"] != "completed"

    def test_incomplete_state_prevents_manual_calculate(self):
        service = CalibrationService()
        with pytest.raises(ValueError, match="not all points are completed"):
            service.calculate_results()

    def test_full_calibration_flow_with_deterministic_samples(self):
        service = CalibrationService()

        targets_mmhg = [0, 50, 100, 150, 200, 250, 300]
        for idx, target in enumerate(targets_mmhg):
            simulated_kpa = mmhg_to_kpa(target)
            service.set_step_samples(idx, [simulated_kpa])

        state = service.get_state()
        assert state["status"] == "completed"
        res = state["results"]
        assert res is not None
        assert pytest.approx(res["gain"], 0.00001) == 1.0
        assert pytest.approx(res["offset"], 0.00001) == 0.0
        assert res["r_squared"] == 1.0
