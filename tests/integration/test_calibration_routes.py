"""Integration tests for calibration routes and /api/calibration/* endpoints."""
from app.services.calibration_service import get_calibration_service, mmhg_to_kpa


class TestCalibrationRoutes:
    def test_calibration_returns_200(self, client):
        response = client.get("/calibration/")
        assert response.status_code == 200

    def test_calibration_contains_heading(self, client):
        response = client.get("/calibration/")
        assert "Calibración del sensor".encode() in response.data

    def test_calibration_nav_link_present(self, client):
        response = client.get("/calibration/")
        assert b"/calibration" in response.data

    def test_calibration_page_loads_script(self, client):
        response = client.get("/calibration/")
        assert b"calibration.js" in response.data


class TestCalibrationApi:
    def test_get_calibration_state(self, client):
        res = client.get("/api/calibration/state")
        assert res.status_code == 200
        data = res.get_json()
        assert "current_step" in data
        assert "total_steps" in data
        assert data["total_steps"] == 7
        assert "points" in data
        assert len(data["points"]) == 7

    def test_start_session(self, client):
        res = client.post("/api/calibration/start")
        assert res.status_code == 200
        data = res.get_json()
        assert data["current_step"] == 0
        assert data["status"] == "in_progress"

    def test_update_observed_point(self, client):
        res = client.post(
            "/api/calibration/update-point",
            json={"step_index": 0, "observed_mmhg": 5.0},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["points"][0]["observed_mmhg"] == 5.0

    def test_measure_step_non_blocking_start(self, client):
        res = client.post(
            "/api/calibration/measure",
            json={"step_index": 0, "target_duration_s": 4.0, "min_samples": 10},
        )
        assert res.status_code == 200
        data = res.get_json()
        pt = data["points"][0]
        assert pt["status"] in ("measuring", "completed")
        assert pt["target_duration_seconds"] == 4.0
        assert pt["min_samples_required"] == 10

    def test_next_and_prev_step(self, client):
        res_next = client.post("/api/calibration/next")
        assert res_next.status_code == 200
        assert res_next.get_json()["current_step"] == 1

        res_prev = client.post("/api/calibration/prev")
        assert res_prev.status_code == 200
        assert res_prev.get_json()["current_step"] == 0

    def test_repeat_step(self, client):
        client.post("/api/calibration/measure", json={"step_index": 0, "target_duration_s": 4.0, "min_samples": 10})
        res = client.post("/api/calibration/repeat", json={"step_index": 0})
        assert res.status_code == 200
        data = res.get_json()
        assert data["points"][0]["status"] == "pending"
        assert data["points"][0]["samples"] == []

    def test_full_calibration_api_flow(self, client):
        client.post("/api/calibration/start")
        service = get_calibration_service()

        targets_mmhg = [0, 50, 100, 150, 200, 250, 300]
        for idx, target in enumerate(targets_mmhg):
            service.set_step_samples(idx, [mmhg_to_kpa(target), mmhg_to_kpa(target)])

        res_state = client.get("/api/calibration/state")
        data = res_state.get_json()
        assert data["status"] == "completed"
        assert data["results"] is not None
        assert "gain" in data["results"]
        assert "offset" in data["results"]
        assert "r_squared" in data["results"]
        assert "residuals" in data["results"]
        assert "repeatability" in data["results"]

    def test_calibration_apply_api_incomplete_calibration_error(self, client):
        client.post("/api/calibration/start")
        res = client.post("/api/calibration/apply")
        assert res.status_code == 400
        data = res.get_json()
        assert "error" in data
        assert "no está completa" in data["error"]

    def test_calibration_apply_api_success(self, client):
        client.post("/api/calibration/start")
        service = get_calibration_service()
        targets_mmhg = [0, 50, 100, 150, 200, 250, 300]
        for idx, target in enumerate(targets_mmhg):
            service.set_step_samples(idx, [mmhg_to_kpa(target)] * 10)

        res = client.post("/api/calibration/apply")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "success"
        assert "calibration" in data
        assert "gain" in data["calibration"]
