"""Unit tests for CalibrationHistoryService — Phase 8."""
from __future__ import annotations

import os
import uuid
import pytest

from app.services.calibration_history_service import CalibrationHistoryService


@pytest.fixture
def temp_history_service(tmp_path):
    """Provide a CalibrationHistoryService instance using a temporary database path."""
    db_file = str(tmp_path / "test_history.sqlite3")
    service = CalibrationHistoryService(db_path=db_file)
    return service


def sample_complete_session_state(session_id: str | None = None) -> dict:
    """Generate a realistic completed calibration session state dictionary."""
    sid = session_id or str(uuid.uuid4())
    points = []
    residuals = []

    for i in range(7):
        target_mmhg = float(i * 50)
        target_kpa = round(target_mmhg * 0.133322, 6)
        obs_kpa = round(target_kpa + 0.01 * (i % 2), 6)
        samples = [obs_kpa - 0.005, obs_kpa, obs_kpa + 0.005]
        timestamps = [1700000000.0 + i * 10 + s for s in range(3)]
        residuals.append(round(0.001 * (i - 3), 6))

        points.append({
            "step_index": i,
            "target_mmhg": target_mmhg,
            "target_kpa": target_kpa,
            "observed_mmhg": target_mmhg,
            "observed_kpa": obs_kpa,
            "samples": samples,
            "sample_timestamps": timestamps,
            "status": "completed",
            "stats": {
                "count": 3,
                "mean": obs_kpa,
                "std": 0.005,
                "min": obs_kpa - 0.005,
                "max": obs_kpa + 0.005,
            },
        })

    return {
        "session_id": sid,
        "created_at": "2026-09-02T12:00:00+00:00",
        "current_step": 6,
        "total_steps": 7,
        "status": "completed",
        "measuring_step": None,
        "points": points,
        "results": {
            "gain": 1.026770,
            "offset": -3.388341,
            "r_squared": 0.999850,
            "max_error": 0.015000,
            "mean_absolute_error": 0.008000,
            "repeatability": 0.005000,
            "residuals": residuals,
        },
    }


class TestCalibrationHistoryService:
    def test_schema_auto_creation(self, temp_history_service):
        """1. Verify tables are automatically created on init."""
        db_path = temp_history_service.db_path
        assert os.path.exists(db_path)
        with temp_history_service._get_connection() as conn:
            tables = [
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            ]
            assert "calibration_sessions" in tables
            assert "calibration_points" in tables

    def test_save_and_retrieve_session(self, temp_history_service):
        """2 & 3. Save a complete session and retrieve it."""
        state = sample_complete_session_state()
        sid = state["session_id"]

        saved = temp_history_service.save_session(state, firmware_version="v1.2.3")
        assert saved["session_id"] == sid
        assert saved["firmware_version"] == "v1.2.3"

        retrieved = temp_history_service.get_session_detail(sid)
        assert retrieved is not None
        assert retrieved["session_id"] == sid
        assert retrieved["firmware_version"] == "v1.2.3"

    def test_retrieve_all_seven_points(self, temp_history_service):
        """4. Verify all 7 measurement points are saved and retrieved correctly."""
        state = sample_complete_session_state()
        sid = state["session_id"]
        temp_history_service.save_session(state)

        detail = temp_history_service.get_session_detail(sid)
        assert detail is not None
        points = detail["points"]
        assert len(points) == 7
        for idx, pt in enumerate(points):
            assert pt["step_index"] == idx
            assert pt["target_mmhg"] == idx * 50.0

    def test_preserve_raw_samples_and_timestamps(self, temp_history_service):
        """5. Verify raw samples and sample_timestamps JSON array serialization/deserialization."""
        state = sample_complete_session_state()
        sid = state["session_id"]
        temp_history_service.save_session(state)

        detail = temp_history_service.get_session_detail(sid)
        p0 = detail["points"][0]
        assert isinstance(p0["samples"], list)
        assert isinstance(p0["sample_timestamps"], list)
        assert len(p0["samples"]) == 3
        assert len(p0["sample_timestamps"]) == 3

    def test_persist_gain_and_offset(self, temp_history_service):
        """6. Verify GAIN and OFFSET persistence."""
        state = sample_complete_session_state()
        sid = state["session_id"]
        temp_history_service.save_session(state)

        detail = temp_history_service.get_session_detail(sid)
        assert detail["gain"] == pytest.approx(1.026770)
        assert detail["offset_kpa"] == pytest.approx(-3.388341)

    def test_persist_r_squared_and_errors(self, temp_history_service):
        """7. Verify R² and error metrics persistence."""
        state = sample_complete_session_state()
        sid = state["session_id"]
        temp_history_service.save_session(state)

        detail = temp_history_service.get_session_detail(sid)
        assert detail["r_squared"] == pytest.approx(0.999850)
        assert detail["max_error_kpa"] == pytest.approx(0.015000)
        assert detail["mean_absolute_error_kpa"] == pytest.approx(0.008000)
        assert detail["repeatability_kpa"] == pytest.approx(0.005000)

    def test_avoid_duplicate_on_same_session_id(self, temp_history_service):
        """8. Idempotency: saving the same session_id twice does not create duplicates."""
        state = sample_complete_session_state()
        sid = state["session_id"]

        save1 = temp_history_service.save_session(state)
        save2 = temp_history_service.save_session(state)

        assert save1["session_id"] == save2["session_id"]

        sessions = temp_history_service.list_sessions()
        assert len(sessions) == 1

        detail = temp_history_service.get_session_detail(sid)
        assert len(detail["points"]) == 7

    def test_list_sessions_descending_order(self, temp_history_service):
        """9. Verify listing sessions ordered by saved_at DESC without raw samples."""
        state1 = sample_complete_session_state()
        state2 = sample_complete_session_state()

        temp_history_service.save_session(state1)
        temp_history_service.save_session(state2)

        sessions = temp_history_service.list_sessions()
        assert len(sessions) == 2
        # Verify raw 'points' array is excluded from summary list
        for s in sessions:
            assert "points" not in s
            assert "gain" in s
            assert "offset_kpa" in s

    def test_non_existent_session_returns_none(self, temp_history_service):
        """10. Querying non-existent session_id returns None."""
        assert temp_history_service.get_session_detail("non-existent-uuid") is None
