"""Unit tests for Phase 5 WebSocket Client (Esp32WebSocketClient).

Tests Protocol v1 compliance & integration readiness:
- Startup mode configuration via environment variables
- Handshake hello -> hello_ack (with strict protocol_version and request_id correlation)
- Telemetry frame parsing & exact single-entry distribution to TelemetryService
- Calibration receiving telemetry without HTTP polling
- HTTP polling not duplicating real samples in websocket mode
- Temporary configuration guard blocking real NVS writing in websocket mode
- Commands & ACK correlation via request_id (ping, get_info, get_calibration, set_calibration, set_telemetry_interval)
- Error frame handling
"""
import json
import os
import threading
import time
import pytest
from websockets.sync.server import serve

from app.services.esp32_client import (
    Esp32WebSocketClient,
    SimulatedEsp32Client,
    get_client_mode,
    get_device_client,
    set_client_mode,
)
from app.services.telemetry_service import TelemetryService, get_service
from app.services.calibration_service import CalibrationService


class TestWebSocketClientStartupAndConfig:
    def test_startup_simulated_by_default(self):
        set_client_mode("simulated")
        assert get_client_mode() == "simulated"
        assert isinstance(get_device_client(), SimulatedEsp32Client)

    def test_startup_websocket_by_configuration(self):
        os.environ["ESP32_CLIENT_MODE"] = "websocket"
        os.environ["ESP32_WS_URL"] = "ws://127.0.0.1:8765/ws"

        set_client_mode("websocket", url="ws://127.0.0.1:8765/ws")
        assert get_client_mode() == "websocket"
        client = get_device_client()
        assert isinstance(client, Esp32WebSocketClient)
        assert client.url == "ws://127.0.0.1:8765/ws"

        set_client_mode("simulated")

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="Modo inválido"):
            set_client_mode("invalid_mode")

    def test_post_config_real_is_blocked_in_websocket_mode(self):
        set_client_mode("websocket", url="ws://127.0.0.1:8765/ws")
        client = get_device_client()

        with pytest.raises(ValueError, match="Escritura real en NVS deshabilitada temporalmente"):
            client.update_config({"gain": 1.5})

        set_client_mode("simulated")


# ── Local Synchronous WebSocket Fake Server ───────────────────────────────

class FakeEsp32Server:
    """Synchronous in-memory WebSocket server mimicking ESP32 Protocol v1 behavior."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.url = f"ws://{host}:{port}/ws"
        self._server = None
        self._thread = None
        self.received_messages: list[dict] = []
        self.fail_set_calibration = False
        self.calib_state = {
            "origin": "NVS",
            "gain": 1.026770,
            "offset_kpa": -3.388341,
            "rtop_ain0_ohm": 32700.0,
            "rbottom_ain0_ohm": 21800.0,
            "rtop_ain1_ohm": 33300.0,
            "rbottom_ain1_ohm": 21500.0,
        }

    def _handler(self, websocket_conn):
        for message in websocket_conn:
            try:
                data = json.loads(message)
            except Exception:
                continue

            self.received_messages.append(data)
            msg_type = data.get("type")
            req_id = data.get("request_id")
            cmd = data.get("command")

            if msg_type == "hello":
                reply = {
                    "type": "hello_ack",
                    "protocol_version": 1,
                    "request_id": req_id,
                    "device": "MonitorO2",
                    "firmware_version": "0.1.0-test",
                    "uptime_ms": 12345,
                }
                websocket_conn.send(json.dumps(reply))

            elif msg_type == "command":
                if cmd == "ping":
                    reply = {
                        "type": "ack",
                        "protocol_version": 1,
                        "request_id": req_id,
                        "command": "ping",
                        "uptime_ms": 12345,
                    }
                    websocket_conn.send(json.dumps(reply))

                elif cmd == "set_telemetry_interval":
                    reply = {
                        "type": "ack",
                        "protocol_version": 1,
                        "request_id": req_id,
                        "command": "set_telemetry_interval",
                        "interval_ms": data.get("interval_ms", 200),
                    }
                    websocket_conn.send(json.dumps(reply))

                elif cmd == "get_info":
                    reply = {
                        "type": "device_info",
                        "protocol_version": 1,
                        "request_id": req_id,
                        "firmware_version": "0.1.0-test",
                        "uptime_ms": 12345,
                        "ads1115_available": True,
                        "ads1115_address": "0x48",
                        "ads1115_rate_sps": 128,
                        "vs_mpx_v": 5.0218,
                        "ocs_frames_ok": 100,
                        "ocs_frames_error": 0,
                        "calibration_origin": self.calib_state.get("origin", "NVS"),
                    }
                    websocket_conn.send(json.dumps(reply))

                elif cmd == "get_calibration":
                    r0 = self.calib_state["rbottom_ain0_ohm"] / (self.calib_state["rtop_ain0_ohm"] + self.calib_state["rbottom_ain0_ohm"])
                    r1 = self.calib_state["rbottom_ain1_ohm"] / (self.calib_state["rtop_ain1_ohm"] + self.calib_state["rbottom_ain1_ohm"])
                    reply = {
                        "type": "calibration",
                        "protocol_version": 1,
                        "request_id": req_id,
                        "calibration_version": 2,
                        "origin": self.calib_state.get("origin", "NVS"),
                        "gain": self.calib_state["gain"],
                        "offset_kpa": self.calib_state["offset_kpa"],
                        "rtop_ain0_ohm": self.calib_state["rtop_ain0_ohm"],
                        "rbottom_ain0_ohm": self.calib_state["rbottom_ain0_ohm"],
                        "rtop_ain1_ohm": self.calib_state["rtop_ain1_ohm"],
                        "rbottom_ain1_ohm": self.calib_state["rbottom_ain1_ohm"],
                        "ratio_ain0": round(r0, 6),
                        "ratio_ain1": round(r1, 6),
                    }
                    websocket_conn.send(json.dumps(reply))

                elif cmd == "set_calibration":
                    if self.fail_set_calibration:
                        reply = {
                            "type": "error",
                            "protocol_version": 1,
                            "request_id": req_id,
                            "code": "validation_error",
                            "message": "PRESSURE_GAIN fuera de rango",
                        }
                    else:
                        cal = data.get("calibration", {})
                        if "gain" in cal: self.calib_state["gain"] = float(cal["gain"])
                        if "offset_kpa" in cal: self.calib_state["offset_kpa"] = float(cal["offset_kpa"])
                        if "rtop_ain0_ohm" in cal: self.calib_state["rtop_ain0_ohm"] = float(cal["rtop_ain0_ohm"])
                        if "rbottom_ain0_ohm" in cal: self.calib_state["rbottom_ain0_ohm"] = float(cal["rbottom_ain0_ohm"])
                        if "rtop_ain1_ohm" in cal: self.calib_state["rtop_ain1_ohm"] = float(cal["rtop_ain1_ohm"])
                        if "rbottom_ain1_ohm" in cal: self.calib_state["rbottom_ain1_ohm"] = float(cal["rbottom_ain1_ohm"])

                        r0 = self.calib_state["rbottom_ain0_ohm"] / (self.calib_state["rtop_ain0_ohm"] + self.calib_state["rbottom_ain0_ohm"])
                        r1 = self.calib_state["rbottom_ain1_ohm"] / (self.calib_state["rtop_ain1_ohm"] + self.calib_state["rbottom_ain1_ohm"])
                        reply = {
                            "type": "ack",
                            "protocol_version": 1,
                            "request_id": req_id,
                            "command": "set_calibration",
                            "status": "nvs_verified",
                            "calibration": {
                                "gain": round(self.calib_state["gain"], 6),
                                "offset_kpa": round(self.calib_state["offset_kpa"], 6),
                                "rtop_ain0_ohm": round(self.calib_state["rtop_ain0_ohm"], 2),
                                "rbottom_ain0_ohm": round(self.calib_state["rbottom_ain0_ohm"], 2),
                                "rtop_ain1_ohm": round(self.calib_state["rtop_ain1_ohm"], 2),
                                "rbottom_ain1_ohm": round(self.calib_state["rbottom_ain1_ohm"], 2),
                                "ratio_ain0": round(r0, 6),
                                "ratio_ain1": round(r1, 6),
                            },
                        }
                    websocket_conn.send(json.dumps(reply))

    def start(self):
        self._server = serve(self._handler, self.host, self.port)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.1)

    def stop(self):
        if self._server:
            self._server.shutdown()


@pytest.fixture
def fake_server():
    server = FakeEsp32Server(port=8765)
    server.start()
    yield server
    server.stop()
    set_client_mode("simulated")


class TestEsp32WebSocketClientProtocol:
    def test_handshake_hello_ack(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        assert client.is_connected() is True

        hello_msgs = [m for m in fake_server.received_messages if m.get("type") == "hello"]
        assert len(hello_msgs) >= 1
        assert hello_msgs[0]["protocol_version"] == 1
        assert hello_msgs[0]["client"] == "monitor-o2-flask"

        client.stop()

    def test_invalid_hello_ack_protocol_version_or_request_id_mismatch(self):
        client = Esp32WebSocketClient(url="ws://127.0.0.1:9999/ws", auto_reconnect=False)
        client._hello_request_id = "req-001"

        # Invalid protocol version
        bad_version_ack = {
            "type": "hello_ack",
            "protocol_version": 99,
            "request_id": "req-001",
            "device": "MonitorO2",
        }
        client._on_message(None, json.dumps(bad_version_ack))
        assert client.is_connected() is False

        # Correlated request_id mismatch
        bad_id_ack = {
            "type": "hello_ack",
            "protocol_version": 1,
            "request_id": "wrong-id",
            "device": "MonitorO2",
        }
        client._on_message(None, json.dumps(bad_id_ack))
        assert client.is_connected() is False

    def test_telemetry_enters_telemetry_service_exactly_once(self):
        set_client_mode("websocket", url="ws://127.0.0.1:8765/ws")
        ws_client = get_device_client()
        telemetry_svc = get_service()
        telemetry_svc._buffer.clear()
        telemetry_svc._latest = None

        frame = {
            "type": "telemetry",
            "protocol_version": 1,
            "seq": 1,
            "o2_pct": 21.0,
            "p_nominal_kpa": 101.3,
        }

        # Simulate receiving 1 WebSocket telemetry frame
        ws_client._on_message(None, json.dumps(frame))

        assert telemetry_svc.buffer_size() == 1
        assert telemetry_svc.get_latest()["o2_pct"] == 21.0
        set_client_mode("simulated")

    def test_polling_http_does_not_duplicate_real_samples(self):
        set_client_mode("websocket", url="ws://127.0.0.1:8765/ws")
        ws_client = get_device_client()
        telemetry_svc = get_service()
        telemetry_svc._buffer.clear()
        telemetry_svc._latest = None

        frame = {
            "type": "telemetry",
            "protocol_version": 1,
            "seq": 1,
            "o2_pct": 20.9,
            "p_nominal_kpa": 101.3,
        }
        ws_client._on_message(None, json.dumps(frame))
        assert telemetry_svc.buffer_size() == 1

        # Simulate 5 HTTP polling calls to tick()
        for _ in range(5):
            s = telemetry_svc.tick()
            assert s["o2_pct"] == 20.9

        # Buffer size MUST stay exactly 1 (no duplicates added!)
        assert telemetry_svc.buffer_size() == 1
        set_client_mode("simulated")

    def test_calibration_receives_telemetry_without_http_polling(self):
        set_client_mode("websocket", url="ws://127.0.0.1:8765/ws")
        ws_client = get_device_client()
        telemetry_svc = get_service()
        ws_client.set_telemetry_callback(telemetry_svc.add_sample)
        calib_svc = CalibrationService()

        # Start step index 0
        calib_svc.start_measuring(step_index=0, target_duration_s=0.01, min_samples=3)
        assert calib_svc.get_state()["points"][0]["status"] == "measuring"

        # Push telemetry frames directly via WebSocket client callback without calling tick() or /api/telemetry
        t0 = time.time()
        for i in range(6):
            frame = {
                "type": "telemetry",
                "protocol_version": 1,
                "seq": i,
                "uptime_ms": 1000 + i * 100,
                "o2_pct": 21.0,
                "flow_l_min": 5.0,
                "temperature_c": 25.0,
                "p_nominal_kpa": 0.0 + i * 0.01,
                "p_calibrated_kpa": 0.0,
                "p_ema_kpa": 0.0,
                "ain0_mv": 1650.0,
                "vs_mpx_v": 5.02,
            }
            # Override _parse_telemetry_frame to inject advancing timestamp
            parsed = ws_client._parse_telemetry_frame(frame)
            parsed["ts"] = t0 + (i * 0.1)
            telemetry_svc.add_sample(parsed)

        # Step MUST progress to completed through subscription without any HTTP polling
        state = calib_svc.get_state()
        assert state["points"][0]["status"] == "completed"
        assert state["points"][0]["samples_received"] >= 3

        set_client_mode("simulated")

    def test_ping_command(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        ack = client.ping()
        assert ack["type"] == "ack"
        assert ack["command"] == "ping"
        assert "uptime_ms" in ack

        client.stop()

    def test_set_telemetry_interval_command(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        ack = client.set_telemetry_interval(100)
        assert ack["type"] == "ack"
        assert ack["command"] == "set_telemetry_interval"
        assert ack["interval_ms"] == 100

        client.stop()

    def test_get_info_command(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        info = client.get_info()
        assert info["type"] == "device_info"
        assert info["firmware_version"] == "0.1.0-test"
        assert info["ads1115_available"] is True

        client.stop()

    def test_get_calibration_command(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        calib = client.get_calibration()
        assert calib["type"] == "calibration"
        assert calib["gain"] == 1.026770
        assert calib["ratio_ain0"] == 0.400000

        client.stop()

    def test_set_calibration_command(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        res = client.set_calibration({
            "gain": 1.5,
            "offset_kpa": 2.0,
            "rtop_ain0_ohm": 32700.0,
            "rbottom_ain0_ohm": 21800.0,
            "rtop_ain1_ohm": 33300.0,
            "rbottom_ain1_ohm": 21500.0,
        })
        assert res["type"] == "ack"
        assert res["status"] == "nvs_verified"
        assert res["calibration"]["gain"] == 1.5

        client.stop()

    def test_error_frame_raises_exception(self, fake_server):
        fake_server.fail_set_calibration = True
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        with pytest.raises(ValueError, match="validation_error"):
            client.set_calibration({"gain": 15.0})

        client.stop()

    def test_telemetry_frame_updates_sample(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)

        received_samples = []
        client.set_telemetry_callback(lambda s: received_samples.append(s))
        client.start()

        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        telemetry_frame = {
            "type": "telemetry",
            "protocol_version": 1,
            "seq": 100,
            "uptime_ms": 12345,
            "o2_pct": 21.4,
            "flow_l_min": 5.2,
            "temperature_c": 24.8,
            "p_nominal_kpa": 101.2,
            "p_calibrated_kpa": 101.5,
            "p_ema_kpa": 101.4,
            "ain0_mv": 1650.0,
            "vs_mpx_v": 5.02,
        }

        # Simulate message arrival
        client._on_message(None, json.dumps(telemetry_frame))

        latest = client.read()
        assert latest["o2_pct"] == 21.4
        assert latest["flow_lpm"] == 5.2
        assert latest["vs_mpx_mv"] == 5020.0
        assert len(received_samples) == 1

        client.stop()


class TestNvsVerificationAndCalibrationApply:
    def test_verify_nvs_write_exact_values(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()
        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        res = client.verify_nvs_write()
        assert res["gain"] == 1.026770
        assert res["offset_kpa"] == -3.388341
        assert res["rtop_ain0_ohm"] == 32700.0
        assert res["rbottom_ain0_ohm"] == 21800.0

        client.stop()

    def test_verify_nvs_write_rejected_if_disconnected(self):
        client = Esp32WebSocketClient(url="ws://127.0.0.1:9999/ws", auto_reconnect=False)
        with pytest.raises(ConnectionError, match="ESP32 no está conectado"):
            client.verify_nvs_write()

    def test_verify_nvs_write_rejected_if_no_nvs_verified_ack(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()
        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        # Mock set_calibration returning status: "failed"
        client.set_calibration = lambda payload: {"type": "ack", "status": "failed"}

        with pytest.raises(RuntimeError, match="Falta confirmación de guardado NVS"):
            client.verify_nvs_write()

        client.stop()

    def test_verify_nvs_write_rejected_if_readback_mismatch(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()
        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        real_set_cal = client.set_calibration

        def set_cal_with_corrupted_readback(payload):
            ack = real_set_cal(payload)
            # Corrupt server state so subsequent get_calibration readback will mismatch
            fake_server.calib_state["gain"] = 9.99999
            return ack

        client.set_calibration = set_cal_with_corrupted_readback

        with pytest.raises(ValueError, match="Fallo de lectura NVS"):
            client.verify_nvs_write()

        client.stop()

    def test_apply_calculated_calibration_preserves_resistors(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()
        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        res = client.apply_calculated_calibration(1.85, 2.5)
        assert res["gain"] == 1.85
        assert res["offset_kpa"] == 2.5
        assert res["rtop_ain0_ohm"] == 32700.0
        assert res["rbottom_ain0_ohm"] == 21800.0
        assert res["rtop_ain1_ohm"] == 33300.0
        assert res["rbottom_ain1_ohm"] == 21500.0

        client.stop()

    def test_no_auto_write_on_calibration_completion(self, fake_server):
        client = Esp32WebSocketClient(url=fake_server.url, auto_reconnect=False)
        client.start()
        for _ in range(20):
            if client.is_connected():
                break
            time.sleep(0.1)

        fake_server.received_messages.clear()
        calib_svc = CalibrationService()
        calib_svc.reset_session()

        # Complete calibration manually
        for idx in range(7):
            calib_svc.set_step_samples(idx, [10.0 + idx] * 10)
        calib_svc.calculate_results()

        assert calib_svc.get_state()["status"] == "completed"

        # Verify NO set_calibration message was sent automatically
        set_cal_msgs = [m for m in fake_server.received_messages if m.get("command") == "set_calibration"]
        assert len(set_cal_msgs) == 0

        client.stop()
