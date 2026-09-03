"""Integration tests for calibration history REST API endpoints — Phase 8."""
from __future__ import annotations

import uuid
import pytest
from unittest.mock import patch, MagicMock

from app import create_app
from app.services.calibration_history_service import (
    get_history_service,
    reset_history_service_for_tests,
    CalibrationHistoryService,
)
from app.services.calibration_service import get_calibration_service


@pytest.fixture
def test_app_with_temp_db(tmp_path):
    """Create test Flask app configured with temporary SQLite DB."""
    reset_history_service_for_tests()
    db_file = str(tmp_path / "integration_history.sqlite3")
    app = create_app({
        "TESTING": True,
        "CALIBRATION_DB_PATH": db_file,
    })
    # Ensure history service is initialized with test DB
    get_history_service(db_path=db_file)
    yield app
    reset_history_service_for_tests()


@pytest.fixture
def client(test_app_with_temp_db):
    return test_app_with_temp_db.test_client()


def populate_dummy_history(db_file: str) -> str:
    """Helper to populate a dummy calibration session in history service."""
    svc = CalibrationHistoryService(db_path=db_file)
    sid = str(uuid.uuid4())
    state = {
        "session_id": sid,
        "created_at": "2026-09-02T12:00:00+00:00",
        "status": "completed",
        "points": [
            {
                "step_index": i,
                "target_mmhg": float(i * 50),
                "target_kpa": round(i * 50 * 0.133322, 6),
                "observed_mmhg": float(i * 50),
                "observed_kpa": round(i * 50 * 0.133322, 6),
                "samples": [1.0, 1.1, 1.2],
                "sample_timestamps": [100.0, 101.0, 102.0],
                "status": "completed",
                "stats": {"count": 3, "mean": 1.1, "std": 0.1, "min": 1.0, "max": 1.2},
            }
            for i in range(7)
        ],
        "results": {
            "gain": 1.02,
            "offset": -3.3,
            "r_squared": 0.999,
            "max_error": 0.01,
            "mean_absolute_error": 0.005,
            "repeatability": 0.002,
            "residuals": [0.001] * 7,
        },
    }
    svc.save_session(state, firmware_version="1.0.0-test")
    return sid


class TestCalibrationHistoryRoutes:
    def test_get_calibration_history_empty(self, client):
        """GET /api/calibration/history returns empty list when no history exists."""
        res = client.get("/api/calibration/history")
        assert res.status_code == 200
        data = res.get_json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_calibration_history_populated(self, client, test_app_with_temp_db):
        """GET /api/calibration/history returns summary list ordered by saved_at DESC."""
        db_file = test_app_with_temp_db.config["CALIBRATION_DB_PATH"]
        sid = populate_dummy_history(db_file)

        res = client.get("/api/calibration/history")
        assert res.status_code == 200
        data = res.get_json()
        assert len(data) == 1
        assert data[0]["session_id"] == sid
        assert data[0]["firmware_version"] == "1.0.0-test"

    def test_get_calibration_history_detail_success(self, client, test_app_with_temp_db):
        """GET /api/calibration/history/<session_id> returns session detail and 7 points."""
        db_file = test_app_with_temp_db.config["CALIBRATION_DB_PATH"]
        sid = populate_dummy_history(db_file)

        res = client.get(f"/api/calibration/history/{sid}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["session_id"] == sid
        assert len(data["points"]) == 7
        assert data["points"][0]["samples"] == [1.0, 1.1, 1.2]

    def test_get_calibration_history_detail_404(self, client):
        """GET /api/calibration/history/<session_id> returns 404 for non-existent ID."""
        res = client.get("/api/calibration/history/unknown-session-id")
        assert res.status_code == 404
        data = res.get_json()
        assert "error" in data

    def test_calibration_apply_saves_history_on_nvs_verified(self, client, test_app_with_temp_db):
        """POST /api/calibration/apply saves history upon successful NVS write."""
        # 1. Setup completed calibration session state
        calib_svc = get_calibration_service()
        calib_svc.reset_session()
        # Mark state completed with dummy results
        calib_svc._status = "completed"
        calib_svc._results = {
            "gain": 1.026770,
            "offset": -3.388341,
            "r_squared": 0.999,
            "max_error": 0.01,
            "mean_absolute_error": 0.005,
            "repeatability": 0.002,
            "residuals": [0.0] * 7,
        }
        for pt in calib_svc._points:
            pt["status"] = "completed"
            pt["samples"] = [1.0, 1.1, 1.2]
            pt["sample_timestamps"] = [100.0, 101.0, 102.0]
            pt["stats"] = {"count": 3, "mean": 1.1, "std": 0.1, "min": 1.0, "max": 1.2}

        # 2. Mock device client so is_connected=True and apply_calculated_calibration succeeds
        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.apply_calculated_calibration.return_value = {
            "gain": 1.026770,
            "offset_kpa": -3.388341,
        }
        mock_client.get_device_info.return_value = {"firmware_version": "v1.2.3"}

        with patch("app.services.esp32_client.get_device_client", return_value=mock_client):
            res = client.post("/api/calibration/apply")
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "success"
            assert data["history_saved"] is True

        # Verify history database now contains this session
        db_file = test_app_with_temp_db.config["CALIBRATION_DB_PATH"]
        history_svc = CalibrationHistoryService(db_path=db_file)
        sessions = history_svc.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["firmware_version"] == "v1.2.3"

    def test_calibration_apply_nvs_ok_sqlite_error_returns_success_with_history_saved_false(self, client, test_app_with_temp_db):
        """POST /api/calibration/apply returns HTTP 200 with history_saved=False if NVS succeeds but SQLite fails."""
        calib_svc = get_calibration_service()
        calib_svc.reset_session()
        calib_svc._status = "completed"
        calib_svc._results = {
            "gain": 1.026770,
            "offset": -3.388341,
            "r_squared": 0.999,
            "max_error": 0.01,
            "mean_absolute_error": 0.005,
            "repeatability": 0.002,
            "residuals": [0.0] * 7,
        }

        mock_client = MagicMock()
        mock_client.is_connected.return_value = True
        mock_client.apply_calculated_calibration.return_value = {
            "gain": 1.026770,
            "offset_kpa": -3.388341,
        }
        mock_client.get_device_info.return_value = {"firmware_version": "v1.2.3"}

        # Force history service save_session to raise an exception
        mock_history_svc = MagicMock()
        mock_history_svc.save_session.side_effect = Exception("SQLite write permission denied")

        with patch("app.services.esp32_client.get_device_client", return_value=mock_client), \
             patch("app.services.calibration_history_service.get_history_service", return_value=mock_history_svc):
            res = client.post("/api/calibration/apply")
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "success"
            assert data["message"] == "Calibración aplicada y verificada en NVS"
            assert data["history_saved"] is False
            assert "history_error" in data
            assert "SQLite write permission denied" in data["history_error"]

    # ── UI & Template Integration Tests ──────────────────────────────────────

    def test_get_calibration_history_page_200(self, client):
        """GET /calibration/history returns HTTP 200 and renders history template."""
        res = client.get("/calibration/history")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Historial de calibraciones" in html
        assert "calibration_history.js" in html

    def test_calibration_history_page_contains_containers(self, client):
        """History page contains table container, detail panel, error alert, and back button."""
        res = client.get("/calibration/history")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'id="history-table-container"' in html
        assert 'id="history-table"' in html
        assert 'id="history-detail-panel"' in html
        assert 'id="detail-points-table"' in html
        assert 'id="btn-back-to-calibration"' in html
        assert 'Volver a calibración' in html

    def test_calibration_page_has_link_to_history(self, client):
        """GET /calibration contains visible navigation link to calibration history."""
        res = client.get("/calibration/")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert "Ver historial de calibraciones" in html
        assert 'href="/calibration/history"' in html

    def test_history_empty_state_elements(self, client):
        """History page has empty state markup with link to start calibration."""
        res = client.get("/calibration/history")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'id="history-empty-state"' in html
        assert "Todavía no hay calibraciones guardadas." in html
        assert 'id="btn-empty-start-calibration"' in html
        assert 'href="/calibration/"' in html

    def test_read_only_guarantees(self, client):
        """History template and JS contain no delete/edit/remove mutation controls."""
        res = client.get("/calibration/history")
        html = res.get_data(as_text=True).lower()
        assert "btn-delete" not in html
        assert "btn-edit" not in html
        assert "eliminar" not in html
        assert "borrar" not in html

    def test_calibration_page_controls_preserved(self, client):
        """Standard calibration page retains all wizard, measure, stepper, and apply controls."""
        res = client.get("/calibration/")
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'id="wizard-card"' in html
        assert 'id="btn-start-measure"' in html
        assert 'id="btn-prev-step"' in html
        assert 'id="btn-repeat-step"' in html
        assert 'id="btn-next-step"' in html
        assert 'id="points-table"' in html
        assert 'id="btn-apply-calibration"' in html

    def test_calibration_js_history_saved_feedback_strings(self):
        """calibration.js contains proper feedback logic for history_saved true and false."""
        import pathlib
        js_path = pathlib.Path("app/static/js/calibration.js")
        content = js_path.read_text(encoding="utf-8")
        assert "La calibración también fue guardada en el historial local." in content
        assert "La calibración fue aplicada al ESP32, pero no pudo guardarse en el historial local." in content
        assert "/calibration/history" in content

