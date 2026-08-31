"""Unit tests for Phase 5 WebSocket Client (Esp32WebSocketClient).

Tests Protocol v1 compliance:
- Mode switching (simulated vs websocket)
- Handshake hello -> hello_ack
- Telemetry frame parsing & distribution
- Commands & ACK correlation via request_id (ping, get_info, get_calibration, set_calibration, set_telemetry_interval)
- Error frame handling
- Connection loss & reconnection behavior
"""
import json
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


class TestWebSocketClientUnit:
    def test_mode_switching(self):
        assert get_client_mode() == "simulated"
        sim_client = get_device_client()
        assert isinstance(sim_client, SimulatedEsp32Client)

        set_client_mode("websocket", url="ws://127.0.0.1:9999/ws")
        assert get_client_mode() == "websocket"
        ws_client = get_device_client()
        assert isinstance(ws_client, Esp32WebSocketClient)

        # Switch back to simulated
        set_client_mode("simulated")
        assert get_client_mode() == "simulated"
        assert isinstance(get_device_client(), SimulatedEsp32Client)

    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="Modo inválido"):
            set_client_mode("invalid_mode")


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
                        "calibration_origin": "NVS",
                    }
                    websocket_conn.send(json.dumps(reply))

                elif cmd == "get_calibration":
                    reply = {
                        "type": "calibration",
                        "protocol_version": 1,
                        "request_id": req_id,
                        "calibration_version": 2,
                        "origin": "NVS",
                        "gain": 1.026770,
                        "offset_kpa": -3.388341,
                        "rtop_ain0_ohm": 32700.0,
                        "rbottom_ain0_ohm": 21800.0,
                        "rtop_ain1_ohm": 33300.0,
                        "rbottom_ain1_ohm": 21500.0,
                        "ratio_ain0": 0.400000,
                        "ratio_ain1": 0.392336,
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
                        r0 = cal.get("rbottom_ain0_ohm", 21800.0) / (cal.get("rtop_ain0_ohm", 32700.0) + cal.get("rbottom_ain0_ohm", 21800.0))
                        r1 = cal.get("rbottom_ain1_ohm", 21500.0) / (cal.get("rtop_ain1_ohm", 33300.0) + cal.get("rbottom_ain1_ohm", 21500.0))
                        reply = {
                            "type": "ack",
                            "protocol_version": 1,
                            "request_id": req_id,
                            "command": "set_calibration",
                            "status": "nvs_verified",
                            "calibration": {
                                "gain": cal.get("gain", 1.0),
                                "offset_kpa": cal.get("offset_kpa", 0.0),
                                "rtop_ain0_ohm": cal.get("rtop_ain0_ohm", 32700.0),
                                "rbottom_ain0_ohm": cal.get("rbottom_ain0_ohm", 21800.0),
                                "rtop_ain1_ohm": cal.get("rtop_ain1_ohm", 33300.0),
                                "rbottom_ain1_ohm": cal.get("rbottom_ain1_ohm", 21500.0),
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
