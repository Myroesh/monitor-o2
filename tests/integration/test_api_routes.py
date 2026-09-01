"""Integration tests for GET /api/telemetry."""
import json
from app.services.esp32_client import set_client_mode, get_device_client
from app.services.telemetry_service import get_service


class TestApiTelemetry:
    URL = "/api/telemetry"

    def test_returns_200(self, client):
        assert client.get(self.URL).status_code == 200

    def test_content_type_json(self, client):
        assert client.get(self.URL).content_type.startswith("application/json")

    def test_has_latest_key(self, client):
        data = client.get(self.URL).get_json()
        assert "latest" in data

    def test_has_history_key(self, client):
        data = client.get(self.URL).get_json()
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_latest_has_required_fields(self, client):
        data = client.get(self.URL).get_json()
        required = {
            "ts", "connected",
            "o2_pct", "flow_lpm", "temp_c",
            "p_nominal_kpa", "p_calibrated_kpa", "p_ema_kpa",
            "ain0_mv", "vs_mpx_mv",
        }
        assert required.issubset(data["latest"].keys())

    def test_connected_true(self, client):
        data = client.get(self.URL).get_json()
        assert data["latest"]["connected"] is True

    def test_o2_plausible_range(self, client):
        data = client.get(self.URL).get_json()
        o2 = data["latest"]["o2_pct"]
        assert isinstance(o2, float)
        assert 15.0 < o2 < 25.0

    def test_history_grows_with_successive_calls(self, client):
        """In simulated mode, each request adds one sample to the history buffer."""
        set_client_mode("simulated")
        for _ in range(3):
            client.get(self.URL)
        data = client.get(self.URL).get_json()
        assert len(data["history"]) >= 4

    def test_history_ordered_oldest_first(self, client):
        """Timestamps in history must be non-decreasing."""
        set_client_mode("simulated")
        for _ in range(5):
            client.get(self.URL)
        history = client.get(self.URL).get_json()["history"]
        timestamps = [s["ts"] for s in history]
        assert timestamps == sorted(timestamps)


class TestApiTelemetryWebSocketIntegration:
    def test_real_singleton_wiring_and_no_duplicates_on_http_polling(self, client):
        """Verifies real application singleton wiring between Esp32WebSocketClient,

        TelemetryService singleton, and /api/telemetry endpoint.
        """
        # 1. Activate websocket mode
        set_client_mode("websocket", url="ws://127.0.0.1:8765/ws")
        ws_client = get_device_client()

        # 2. Get real application singleton
        service = get_service()

        # Clear singleton buffer for deterministic test
        service._buffer.clear()
        service._latest = None

        # 3. Simulate 3 incoming WebSocket telemetry frames
        for seq in [1, 2, 3]:
            frame = {
                "type": "telemetry",
                "protocol_version": 1,
                "seq": seq,
                "uptime_ms": 1000 * seq,
                "o2_pct": 21.0 + seq,
                "flow_l_min": 5.0,
                "temperature_c": 25.0,
                "p_nominal_kpa": 101.3,
            }
            ws_client._on_message(None, json.dumps(frame))

        # 4. Verify real singleton state
        assert service.buffer_size() == 3
        assert len(service.get_history()) == 3
        assert service.get_latest()["seq"] == 3

        # 5. Perform multiple HTTP queries to /api/telemetry
        for _ in range(5):
            resp = client.get("/api/telemetry")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["latest"]["seq"] == 3
            assert len(data["history"]) == 3

        # 6. Verify buffer still has EXACTLY 3 samples (no duplicates added on HTTP polling!)
        assert service.buffer_size() == 3
        assert len(service.get_history()) == 3

        # Reset mode to simulated
        set_client_mode("simulated")
