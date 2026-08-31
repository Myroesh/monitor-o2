"""Integration tests for GET /api/telemetry."""


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
        """Each request adds one sample to the history buffer."""
        for _ in range(3):
            client.get(self.URL)
        data = client.get(self.URL).get_json()
        assert len(data["history"]) >= 4

    def test_history_ordered_oldest_first(self, client):
        """Timestamps in history must be non-decreasing."""
        for _ in range(5):
            client.get(self.URL)
        history = client.get(self.URL).get_json()["history"]
        timestamps = [s["ts"] for s in history]
        assert timestamps == sorted(timestamps)
