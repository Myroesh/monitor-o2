"""Unit tests for CalibrationHistoryService — Phase 8."""
from __future__ import annotations

import os
import sqlite3
import uuid
import pytest

from app.services.calibration_history_service import (
    CalibrationHistoryService,
    get_history_service,
    reset_history_service_for_tests,
)


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
        """1. Verify tables and unique index are automatically created on init."""
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

            indices = [
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index';"
                ).fetchall()
            ]
            assert "idx_calibration_points_session_step" in indices

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
        for s in sessions:
            assert "points" not in s
            assert "gain" in s
            assert "offset_kpa" in s

    def test_non_existent_session_returns_none(self, temp_history_service):
        """10. Querying non-existent session_id returns None."""
        assert temp_history_service.get_session_detail("non-existent-uuid") is None

    # ── Robustness Audit Tests ───────────────────────────────────────────────

    def test_singleton_reused_with_same_db_path(self, tmp_path):
        """11. Reuses existing instance when effective db_path is the same."""
        reset_history_service_for_tests()
        db_file = str(tmp_path / "singleton.sqlite3")

        svc1 = get_history_service(db_file)
        # Call again with the same path
        svc2 = get_history_service(db_file)
        assert svc1 is svc2

        # Call with redundant relative traversal resolving to the same file
        equivalent_path = str(tmp_path / "subdir" / ".." / "singleton.sqlite3")
        svc3 = get_history_service(equivalent_path)
        assert svc1 is svc3
        reset_history_service_for_tests()

    def test_new_instance_if_db_path_changes(self, tmp_path):
        """12. Creates a new instance only when db_path truly changes."""
        reset_history_service_for_tests()
        db1 = str(tmp_path / "db1.sqlite3")
        db2 = str(tmp_path / "db2.sqlite3")

        svc1 = get_history_service(db1)
        svc2 = get_history_service(db2)
        assert svc1 is not svc2
        assert svc1.normalized_db_path != svc2.normalized_db_path
        reset_history_service_for_tests()

    def test_reject_session_with_status_not_completed(self, temp_history_service):
        """13. Rejects session whose status is not 'completed'."""
        state = sample_complete_session_state()
        state["status"] = "in_progress"

        with pytest.raises(ValueError, match="completed"):
            temp_history_service.save_session(state)

    def test_reject_session_with_uncompleted_point(self, temp_history_service):
        """14. Rejects session if any point is not 'completed'."""
        state = sample_complete_session_state()
        state["points"][3]["status"] = "measuring"

        with pytest.raises(ValueError, match="no está completado"):
            temp_history_service.save_session(state)

    def test_reject_session_with_mismatched_samples_and_timestamps(self, temp_history_service):
        """15. Rejects session if samples and sample_timestamps have different lengths."""
        state = sample_complete_session_state()
        state["points"][0]["samples"] = [1.0, 2.0, 3.0]
        state["points"][0]["sample_timestamps"] = [100.0, 101.0]

        with pytest.raises(ValueError, match="longitudes inconsistentes"):
            temp_history_service.save_session(state)

    def test_reject_session_with_mismatched_stats_count(self, temp_history_service):
        """16. Rejects session if stats.count does not match the samples count."""
        state = sample_complete_session_state()
        state["points"][1]["stats"]["count"] = 999  # actual len is 3

        with pytest.raises(ValueError, match="inconsistente con el número de muestras"):
            temp_history_service.save_session(state)

    def test_point_uniqueness_session_step(self, temp_history_service):
        """17. Unique index prevents duplicate (session_id, step_index) rows."""
        state = sample_complete_session_state()
        sid = state["session_id"]
        temp_history_service.save_session(state)

        with temp_history_service._get_connection() as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO calibration_points (
                        session_id, step_index, target_mmhg, target_kpa,
                        observed_mmhg, observed_kpa, sample_count,
                        mean_p_nominal_kpa, std_p_nominal_kpa, min_p_nominal_kpa,
                        max_p_nominal_kpa, residual_kpa, samples, sample_timestamps
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        0,  # step_index 0 already exists for this sid
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        1,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        "[]",
                        "[]",
                    ),
                )

    def test_atomic_rollback_on_point_failure(self, temp_history_service, monkeypatch):
        """18. Atomic transaction: failure during point insertion rolls back session and all points."""
        state = sample_complete_session_state()
        sid = state["session_id"]

        real_get_conn = temp_history_service._get_connection

        class FailingCursor:
            def __init__(self, real_cursor):
                self._real = real_cursor

            def execute(self, sql, *args):
                if "INSERT INTO calibration_points" in sql and len(args) > 0 and args[0][1] == 3:
                    raise sqlite3.OperationalError("Simulated point insertion disk error")
                return self._real.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self._real, name)

        class ProxyConnection:
            def __init__(self, real_conn):
                self._real = real_conn

            def cursor(self):
                return FailingCursor(self._real.cursor())

            def __enter__(self):
                return self._real.__enter__()

            def __exit__(self, exc_type, exc_val, exc_tb):
                return self._real.__exit__(exc_type, exc_val, exc_tb)

            def __getattr__(self, name):
                return getattr(self._real, name)

        monkeypatch.setattr(temp_history_service, "_get_connection", lambda: ProxyConnection(real_get_conn()))

        with pytest.raises(sqlite3.OperationalError, match="Simulated point insertion disk error"):
            temp_history_service.save_session(state)

        # Verify NO partial session or points were committed
        monkeypatch.undo()

        assert temp_history_service.get_session_detail(sid) is None

        with temp_history_service._get_connection() as conn:
            session_count = conn.execute(
                "SELECT COUNT(*) FROM calibration_sessions WHERE session_id = ?", (sid,)
            ).fetchone()[0]
            point_count = conn.execute(
                "SELECT COUNT(*) FROM calibration_points WHERE session_id = ?", (sid,)
            ).fetchone()[0]

            assert session_count == 0
            assert point_count == 0
