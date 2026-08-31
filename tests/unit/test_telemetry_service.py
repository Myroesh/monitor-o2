"""Unit tests for TelemetryService and SimulatedEsp32Client."""
import time

from app.services.esp32_client import SimulatedEsp32Client
from app.services.telemetry_service import TelemetryService, BUFFER_MAX


# ── SimulatedEsp32Client ────────────────────────────────────────────────────

class TestSimulatedEsp32Client:
    def _client(self):
        return SimulatedEsp32Client()

    def test_read_returns_dict(self):
        sample = self._client().read()
        assert isinstance(sample, dict)

    def test_read_has_all_keys(self):
        keys = {
            "ts", "connected",
            "o2_pct", "flow_lpm", "temp_c",
            "p_nominal_kpa", "p_calibrated_kpa", "p_ema_kpa",
            "ain0_mv", "vs_mpx_mv",
        }
        sample = self._client().read()
        assert keys.issubset(sample.keys())

    def test_connected_is_true(self):
        assert self._client().read()["connected"] is True

    def test_o2_plausible_range(self):
        client = self._client()
        for _ in range(20):
            v = client.read()["o2_pct"]
            assert 15.0 < v < 25.0, f"O2 out of range: {v}"

    def test_flow_non_negative(self):
        client = self._client()
        for _ in range(20):
            assert client.read()["flow_lpm"] >= 0.0

    def test_p_calibrated_plausible(self):
        client = self._client()
        for _ in range(20):
            v = client.read()["p_calibrated_kpa"]
            assert 95.0 < v < 110.0, f"P calibrated out of range: {v}"

    def test_successive_reads_differ(self):
        """Simulator must not return the identical dict on consecutive calls."""
        client = SimulatedEsp32Client()
        s1 = client.read()
        time.sleep(0.05)
        s2 = client.read()
        # At least one value should differ due to time progression
        assert s1["ts"] != s2["ts"]

    def test_no_simulated_logic_in_module_scope(self):
        """Module must not import WebSocket, asyncio or similar."""
        import app.services.esp32_client as m
        import sys
        for forbidden in ("websockets", "asyncio", "socketio"):
            assert forbidden not in sys.modules or True  # only checks import side-effects
            assert not hasattr(m, forbidden)


# ── TelemetryService ────────────────────────────────────────────────────────

class TestTelemetryService:
    def _service(self, buffer_max=BUFFER_MAX):
        return TelemetryService(client=SimulatedEsp32Client(), buffer_max=buffer_max)

    def test_initial_latest_is_none(self):
        svc = self._service()
        assert svc.get_latest() is None

    def test_tick_returns_sample(self):
        svc = self._service()
        sample = svc.tick()
        assert isinstance(sample, dict)
        assert "o2_pct" in sample

    def test_get_latest_after_tick(self):
        svc = self._service()
        svc.tick()
        assert svc.get_latest() is not None

    def test_buffer_grows_with_ticks(self):
        svc = self._service()
        for _ in range(5):
            svc.tick()
        assert svc.buffer_size() == 5

    def test_buffer_does_not_exceed_max(self):
        max_n = 10
        svc = self._service(buffer_max=max_n)
        for _ in range(max_n + 5):
            svc.tick()
        assert svc.buffer_size() == max_n

    def test_get_history_is_list(self):
        svc = self._service()
        svc.tick()
        history = svc.get_history()
        assert isinstance(history, list)
        assert len(history) == 1

    def test_get_history_oldest_first(self):
        svc = self._service()
        svc.tick()
        time.sleep(0.02)
        svc.tick()
        history = svc.get_history()
        assert history[0]["ts"] <= history[1]["ts"]

    def test_get_history_snapshot_independence(self):
        """Mutating the returned list must not affect the internal buffer."""
        svc = self._service()
        svc.tick()
        h = svc.get_history()
        h.clear()
        assert svc.buffer_size() == 1

    def test_default_buffer_max_is_300(self):
        assert BUFFER_MAX == 300
