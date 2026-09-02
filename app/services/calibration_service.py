"""Calibration service — Phase 3 (Audited & Refined).

Handles guided sensor calibration math, target points, event-driven sample collection,
and least-squares linear regression calculations.

Samples are captured over a configurable time window (default 4.0s) with a minimum
sample count criteria (default 10 samples), using timestamps to compute effective frequency.
Consumes telemetry samples as they arrive over time from TelemetryService without sleep().
"""
from __future__ import annotations

import datetime
import math
import threading
import time
import uuid
from typing import Any

from app.services.telemetry_service import get_service

# Exact conversion factor specified by requirements
MMHG_TO_KPA = 0.133322

# Default calibration target points in mmHg
DEFAULT_TARGET_POINTS_MMHG = [0, 50, 100, 150, 200, 250, 300]

# Default time-window capture configuration
DEFAULT_TARGET_DURATION_S = 4.0
DEFAULT_MIN_SAMPLES_REQUIRED = 10
MAX_MEASURE_TIMEOUT_S = 15.0


def mmhg_to_kpa(mmhg: float) -> float:
    """Convert pressure from mmHg to kPa using exact factor 0.133322."""
    return mmhg * MMHG_TO_KPA


def calculate_sample_stats(samples: list[float]) -> dict[str, float | int]:
    """Calculate summary statistics for a list of raw numeric samples.

    Returns mean, sample standard deviation (unbiased, N-1), min, max, and count.
    Handles count == 0 and count == 1 safely (std = 0.0).
    """
    if not samples:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}

    n = len(samples)
    mean_val = sum(samples) / n

    if n > 1:
        variance = sum((x - mean_val) ** 2 for x in samples) / (n - 1)
        std_val = math.sqrt(max(0.0, variance))
    else:
        std_val = 0.0

    return {
        "mean": round(mean_val, 6),
        "std": round(std_val, 6),
        "min": round(min(samples), 6),
        "max": round(max(samples), 6),
        "count": n,
    }


def fit_linear_regression(x_values: list[float], y_values: list[float]) -> dict[str, Any]:
    """Perform Ordinary Least Squares (OLS) linear regression: y = GAIN * x + OFFSET.

    x_values: Measured sensor values (e.g. mean P_nominal in kPa)
    y_values: Reference values (observed real pressure in kPa)
    """
    n = len(x_values)
    if n < 2:
        raise ValueError("Linear regression requires at least 2 data points.")

    if len(x_values) != len(y_values):
        raise ValueError("x_values and y_values must have the same length.")

    mean_x = sum(x_values) / n
    mean_y = sum(y_values) / n

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    denominator = sum((x - mean_x) ** 2 for x in x_values)

    if denominator == 0:
        gain = 1.0
        offset = 0.0
    else:
        gain = numerator / denominator
        offset = mean_y - gain * mean_x

    # Fitted values: y_pred_i = gain * x_i + offset
    y_pred = [gain * x + offset for x in x_values]

    # Residuals & point errors: y_i - y_pred_i
    residuals = [y - yp for y, yp in zip(y_values, y_pred)]
    point_errors = residuals
    abs_errors = [abs(e) for e in residuals]

    max_error = max(abs_errors) if abs_errors else 0.0
    mean_absolute_error = sum(abs_errors) / n if n > 0 else 0.0

    # Coefficient of determination R² = 1 - (SSE / SST)
    sst = sum((y - mean_y) ** 2 for y in y_values)
    sse = sum((y - yp) ** 2 for y, yp in zip(y_values, y_pred))

    if sst == 0:
        r_squared = 1.0
    else:
        r_squared = max(0.0, 1.0 - (sse / sst))

    return {
        "gain": round(gain, 6),
        "offset": round(offset, 6),
        "r_squared": round(r_squared, 6),
        "residuals": [round(r, 6) for r in residuals],
        "point_errors": [round(e, 6) for e in point_errors],
        "max_error": round(max_error, 6),
        "mean_absolute_error": round(mean_absolute_error, 6),
    }


class CalibrationService:
    """Thread-safe state machine and manager for calibration sessions.

    Consumes telemetry samples asynchronously over a time window.
    """

    def __init__(self, target_points: list[float] | None = None) -> None:
        self._lock = threading.Lock()
        self._target_points = list(target_points or DEFAULT_TARGET_POINTS_MMHG)
        self._measuring_step: int | None = None
        self.reset_session()

        # Subscribe to telemetry service listener
        get_service().subscribe(self.on_telemetry_sample)

    def reset_session(self) -> dict[str, Any]:
        """Initialize or reset a calibration session."""
        with self._lock:
            self._session_id = str(uuid.uuid4())
            self._created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self._current_step = 0
            self._measuring_step = None
            self._status = "in_progress"
            self._points: list[dict[str, Any]] = []

            for i, target in enumerate(self._target_points):
                self._points.append({
                    "step_index": i,
                    "target_mmhg": float(target),
                    "target_kpa": round(mmhg_to_kpa(float(target)), 6),
                    "observed_mmhg": float(target),
                    "observed_kpa": round(mmhg_to_kpa(float(target)), 6),
                    "samples": [],
                    "sample_timestamps": [],
                    "start_time": None,
                    "target_duration_s": DEFAULT_TARGET_DURATION_S,
                    "min_samples_required": DEFAULT_MIN_SAMPLES_REQUIRED,
                    "stats": calculate_sample_stats([]),
                    "status": "pending",
                })

            self._results: dict[str, Any] | None = None
            return self._get_state_unlocked()

    def on_telemetry_sample(self, sample: dict) -> None:
        """Callback invoked whenever TelemetryService receives or generates a new sample."""
        with self._lock:
            if self._measuring_step is None:
                return

            step_idx = self._measuring_step
            if not (0 <= step_idx < len(self._points)):
                self._measuring_step = None
                return

            pt = self._points[step_idx]
            p_val = sample.get("p_nominal_kpa", 0.0)
            sample_ts = sample.get("ts", time.time())

            if pt["start_time"] is None:
                pt["start_time"] = sample_ts

            pt["samples"].append(p_val)
            pt["sample_timestamps"].append(sample_ts)
            pt["stats"] = calculate_sample_stats(pt["samples"])

            # Compute elapsed time and check completion criteria
            elapsed_s = max(0.0, sample_ts - pt["start_time"])
            samples_count = len(pt["samples"])

            # Check if duration target AND minimum samples requirement are met
            if elapsed_s >= pt["target_duration_s"] and samples_count >= pt["min_samples_required"]:
                pt["status"] = "completed"
                self._measuring_step = None

                # Auto-calculate results if all steps completed
                if all(p["status"] == "completed" for p in self._points):
                    self._calculate_results_unlocked()
                    self._status = "completed"
            elif elapsed_s >= MAX_MEASURE_TIMEOUT_S and samples_count < pt["min_samples_required"]:
                # Timeout error: window expired without reaching minimum required samples
                pt["status"] = "insufficient_samples"
                self._measuring_step = None

    def get_state(self) -> dict[str, Any]:
        """Return a copy of the current calibration session state."""
        with self._lock:
            return self._get_state_unlocked()

    def _get_state_unlocked(self) -> dict[str, Any]:
        now_ts = time.time()
        points_copy = []

        for p in self._points:
            p_dict = dict(p)
            p_dict["samples"] = list(p["samples"])
            p_dict["sample_timestamps"] = list(p.get("sample_timestamps", []))
            p_dict["stats"] = dict(p["stats"])

            timestamps = p_dict["sample_timestamps"]
            samples_received = len(p_dict["samples"])

            # Calculate elapsed time and effective frequency
            if p["status"] == "measuring":
                start_t = p["start_time"] or now_ts
                elapsed_s = max(0.0, now_ts - start_t)
            elif timestamps and len(timestamps) > 1:
                elapsed_s = max(0.0, timestamps[-1] - timestamps[0])
            else:
                elapsed_s = 0.0

            if len(timestamps) >= 2 and (timestamps[-1] - timestamps[0]) > 0:
                eff_hz = (len(timestamps) - 1) / (timestamps[-1] - timestamps[0])
            elif elapsed_s > 0 and samples_received > 0:
                eff_hz = samples_received / elapsed_s
            else:
                eff_hz = 0.0

            target_dur = p.get("target_duration_s", DEFAULT_TARGET_DURATION_S)
            p_dict["samples_received"] = samples_received
            p_dict["elapsed_seconds"] = round(elapsed_s, 2)
            p_dict["target_duration_seconds"] = target_dur
            p_dict["min_samples_required"] = p.get("min_samples_required", DEFAULT_MIN_SAMPLES_REQUIRED)
            p_dict["effective_frequency_hz"] = round(eff_hz, 2)

            if p["status"] == "completed":
                p_dict["progress"] = 1.0
            elif p["status"] == "measuring" and target_dur > 0:
                p_dict["progress"] = round(min(1.0, elapsed_s / target_dur), 2)
            else:
                p_dict["progress"] = 0.0

            points_copy.append(p_dict)

        return {
            "session_id": getattr(self, "_session_id", None),
            "created_at": getattr(self, "_created_at", None),
            "current_step": self._current_step,
            "total_steps": len(self._points),
            "status": self._status,
            "measuring_step": self._measuring_step,
            "points": points_copy,
            "results": dict(self._results) if self._results else None,
        }

    def start_measuring(self, step_index: int, target_duration_s: float = DEFAULT_TARGET_DURATION_S, min_samples: int = DEFAULT_MIN_SAMPLES_REQUIRED) -> dict[str, Any]:
        """Start non-blocking sample collection over a time window for the specified step."""
        with self._lock:
            if not (0 <= step_index < len(self._points)):
                raise IndexError(f"Invalid step index: {step_index}")

            pt = self._points[step_index]
            pt["samples"] = []
            pt["sample_timestamps"] = []
            pt["start_time"] = time.time()
            pt["target_duration_s"] = max(0.5, float(target_duration_s))
            pt["min_samples_required"] = max(1, int(min_samples))
            pt["stats"] = calculate_sample_stats([])
            pt["status"] = "measuring"

            self._measuring_step = step_index
            self._current_step = step_index
            self._status = "in_progress"
            self._results = None

            return self._get_state_unlocked()

    def capture_step_samples(self, step_index: int, sample_count: int = 10, duration_s: float = 4.0) -> dict[str, Any]:
        """Convenience method: starts measuring and feeds simulated samples for testing."""
        self.start_measuring(step_index, target_duration_s=duration_s, min_samples=sample_count)
        # Advance ticks with timestamp increment to satisfy duration >= duration_s and count >= sample_count
        start_ts = time.time()
        step_dt = duration_s / max(1, sample_count)

        for i in range(sample_count):
            t_sample = start_ts + (i + 1) * step_dt
            get_service().add_sample({"ts": t_sample, "p_nominal_kpa": 100.0 + i})

        return self.get_state()

    def set_step_samples(self, step_index: int, samples: list[float]) -> dict[str, Any]:
        """Directly set explicit samples for a step (used in deterministic tests)."""
        with self._lock:
            if not (0 <= step_index < len(self._points)):
                raise IndexError(f"Invalid step index: {step_index}")

            pt = self._points[step_index]
            pt["samples"] = list(samples)
            now = time.time()
            pt["sample_timestamps"] = [now + i * 0.1 for i in range(len(samples))]
            pt["stats"] = calculate_sample_stats(samples)
            pt["status"] = "completed"

            if self._measuring_step == step_index:
                self._measuring_step = None

            if all(p["status"] == "completed" for p in self._points):
                self._calculate_results_unlocked()
                self._status = "completed"

            return self._get_state_unlocked()

    def update_observed_pressure(self, step_index: int, observed_mmhg: float) -> dict[str, Any]:
        """Update the user-observed real pressure for a step."""
        with self._lock:
            if not (0 <= step_index < len(self._points)):
                raise IndexError(f"Invalid step index: {step_index}")

            pt = self._points[step_index]
            pt["observed_mmhg"] = float(observed_mmhg)
            pt["observed_kpa"] = round(mmhg_to_kpa(float(observed_mmhg)), 6)

            if self._status == "completed" or all(p["status"] == "completed" for p in self._points):
                self._calculate_results_unlocked()

            return self._get_state_unlocked()

    def next_step(self) -> dict[str, Any]:
        """Advance wizard to next step."""
        with self._lock:
            if self._current_step < len(self._points) - 1:
                self._current_step += 1
            elif all(p["status"] == "completed" for p in self._points):
                self._calculate_results_unlocked()
                self._status = "completed"
            return self._get_state_unlocked()

    def previous_step(self) -> dict[str, Any]:
        """Go back to previous step."""
        with self._lock:
            if self._current_step > 0:
                self._current_step -= 1
            return self._get_state_unlocked()

    def repeat_step(self, step_index: int) -> dict[str, Any]:
        """Reset samples for a step and move wizard focus back to it."""
        with self._lock:
            if not (0 <= step_index < len(self._points)):
                raise IndexError(f"Invalid step index: {step_index}")

            pt = self._points[step_index]
            pt["samples"] = []
            pt["sample_timestamps"] = []
            pt["start_time"] = None
            pt["stats"] = calculate_sample_stats([])
            pt["status"] = "pending"

            if self._measuring_step == step_index:
                self._measuring_step = None

            self._current_step = step_index
            self._status = "in_progress"
            self._results = None
            return self._get_state_unlocked()

    def calculate_results(self) -> dict[str, Any]:
        """Explicitly calculate linear regression results."""
        with self._lock:
            if any(p["status"] != "completed" for p in self._points):
                raise ValueError("Cannot calculate results: not all points are completed.")
            self._calculate_results_unlocked()
            self._status = "completed"
            return self._get_state_unlocked()

    def _calculate_results_unlocked(self) -> None:
        """Internal helper to compute linear regression."""
        x_vals = [p["stats"]["mean"] for p in self._points]
        y_vals = [p["observed_kpa"] for p in self._points]

        reg = fit_linear_regression(x_vals, y_vals)

        stds = [p["stats"]["std"] for p in self._points]
        repeatability = round(sum(stds) / len(stds), 6) if stds else 0.0

        self._results = {
            "gain": reg["gain"],
            "offset": reg["offset"],
            "r_squared": reg["r_squared"],
            "residuals": reg["residuals"],
            "point_errors": reg["point_errors"],
            "max_error": reg["max_error"],
            "mean_absolute_error": reg["mean_absolute_error"],
            "repeatability": repeatability,
        }


# Module-level singleton
_calibration_service = CalibrationService()


def get_calibration_service() -> CalibrationService:
    """Return application-level CalibrationService instance."""
    return _calibration_service
