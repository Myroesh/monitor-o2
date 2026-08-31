"""ESP32 WebSocket client & Simulator — Phase 2, Phase 4 & Phase 5.

Provides both:
1. Esp32WebSocketClient: Real WebSocket client implementing Protocol v1 (ws://192.168.4.1/ws).
2. SimulatedEsp32Client: Simulated client for offline development & unit tests.

This module is the ONLY layer that knows about the ESP32 WebSocket protocol.
"""
from __future__ import annotations

import json
import math
import random
import threading
import time
from typing import Any, Callable

try:
    import websocket
except ImportError:
    websocket = None


PROTOCOL_VERSION = 1
DEFAULT_WS_URL = "ws://192.168.4.1/ws"


class SimulatedEsp32Client:
    """Generates simulated telemetry and manages simulated ESP32 configuration."""

    # Simulation centre-points and small noise amplitudes
    _O2_BASE = 20.9          # %  — atmospheric O2
    _FLOW_BASE = 5.0         # L/min
    _TEMP_BASE = 25.0        # °C
    _P_NOMINAL_BASE = 101.3  # kPa — roughly sea-level
    _P_CALIB_BASE = 101.3    # kPa
    _P_EMA_BASE = 101.3      # kPa — EMA follows calibrated
    _AIN0_MV_BASE = 1650.0   # mV  — midpoint of a 3.3V ADC
    _VS_MPX_BASE = 5020.0    # mV  — MPX5500DP supply voltage (~5V)

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._t0 = time.monotonic()

        # Simulated device info & configuration parameters
        self._firmware_version = "v1.2.0-sim"
        self._ads1115_status = "OK"
        self._ads1115_i2c_address = "0x48"
        self._ads1115_data_rate = "128 SPS"
        self._calibration_origin = "Simulado (en memoria)"

        # Default calibration & hardware parameters matching actual firmware
        self._gain = 1.026770
        self._offset = -3.388341
        self._rtop_ain0 = 32700.0      # Ohms
        self._rbottom_ain0 = 21800.0   # Ohms
        self._rtop_ain1 = 33300.0      # Ohms
        self._rbottom_ain1 = 21500.0   # Ohms

        # Frame counters
        self._ocs3f_frames_ok = 14520
        self._ocs3f_frames_error = 2
        self._telemetry_callback: Callable[[dict], None] | None = None

    def set_telemetry_callback(self, callback: Callable[[dict], None]) -> None:
        """Register a callback for incoming telemetry samples."""
        self._telemetry_callback = callback

    def is_connected(self) -> bool:
        """Returns True for simulated client."""
        return True

    def _t(self) -> float:
        return time.monotonic() - self._t0

    def read(self) -> dict[str, Any]:
        """Return one simulated telemetry sample."""
        t = self._t()

        with self._lock:
            gain = self._gain
            offset = self._offset

        # Slow sine wave + small random jitter for each variable
        o2 = self._O2_BASE + 0.3 * math.sin(t / 12) + random.gauss(0, 0.05)
        flow = self._FLOW_BASE + 0.5 * math.sin(t / 8 + 1) + random.gauss(0, 0.02)
        temp = self._TEMP_BASE + 0.8 * math.sin(t / 30) + random.gauss(0, 0.05)
        p_nominal = self._P_NOMINAL_BASE + 0.2 * math.sin(t / 20) + random.gauss(0, 0.02)
        p_calibrated = (p_nominal * gain) + offset + random.gauss(0, 0.03)
        p_ema = self._P_EMA_BASE + 0.35 * math.sin(t / 15 + 0.6) + random.gauss(0, 0.01)
        ain0_mv = self._AIN0_MV_BASE + 10 * math.sin(t / 10) + random.gauss(0, 0.5)
        vs_mpx = self._VS_MPX_BASE + 5 * math.sin(t / 60) + random.gauss(0, 0.2)

        sample = {
            "ts": round(time.time(), 3),
            "connected": True,
            "o2_pct": round(o2, 3),
            "flow_lpm": round(max(flow, 0.0), 3),
            "temp_c": round(temp, 3),
            "p_nominal_kpa": round(p_nominal, 4),
            "p_calibrated_kpa": round(p_calibrated, 4),
            "p_ema_kpa": round(p_ema, 4),
            "ain0_mv": round(ain0_mv, 2),
            "vs_mpx_mv": round(vs_mpx, 2),
        }

        if self._telemetry_callback:
            try:
                self._telemetry_callback(sample)
            except Exception:
                pass

        return sample

    def ping(self) -> dict[str, Any]:
        """Simulated ping command."""
        return {
            "type": "ack",
            "protocol_version": PROTOCOL_VERSION,
            "command": "ping",
            "uptime_ms": int((time.monotonic() - self._t0) * 1000),
        }

    def set_telemetry_interval(self, interval_ms: int) -> dict[str, Any]:
        """Simulated set_telemetry_interval command."""
        return {
            "type": "ack",
            "protocol_version": PROTOCOL_VERSION,
            "command": "set_telemetry_interval",
            "interval_ms": interval_ms,
        }

    def get_calibration(self) -> dict[str, Any]:
        """Simulated get_calibration command."""
        with self._lock:
            ratio_ain0 = self._rbottom_ain0 / (self._rtop_ain0 + self._rbottom_ain0)
            ratio_ain1 = self._rbottom_ain1 / (self._rtop_ain1 + self._rbottom_ain1)
            return {
                "type": "calibration",
                "protocol_version": PROTOCOL_VERSION,
                "calibration_version": 2,
                "origin": self._calibration_origin,
                "gain": round(self._gain, 6),
                "offset_kpa": round(self._offset, 6),
                "rtop_ain0_ohm": round(self._rtop_ain0, 2),
                "rbottom_ain0_ohm": round(self._rbottom_ain0, 2),
                "rtop_ain1_ohm": round(self._rtop_ain1, 2),
                "rbottom_ain1_ohm": round(self._rbottom_ain1, 2),
                "ratio_ain0": round(ratio_ain0, 6),
                "ratio_ain1": round(ratio_ain1, 6),
            }

    def set_calibration(self, calibration: dict[str, Any]) -> dict[str, Any]:
        """Simulated set_calibration command."""
        return self.update_config({
            "gain": calibration.get("gain", self._gain),
            "offset": calibration.get("offset_kpa", self._offset),
            "rtop_ain0": calibration.get("rtop_ain0_ohm", self._rtop_ain0),
            "rbottom_ain0": calibration.get("rbottom_ain0_ohm", self._rbottom_ain0),
            "rtop_ain1": calibration.get("rtop_ain1_ohm", self._rtop_ain1),
            "rbottom_ain1": calibration.get("rbottom_ain1_ohm", self._rbottom_ain1),
        })

    def get_device_info(self) -> dict[str, Any]:
        """Return full device status, hardware parameters, and calibration configuration."""
        with self._lock:
            uptime = int(time.monotonic() - self._t0)
            ratio_ain0 = self._rbottom_ain0 / (self._rtop_ain0 + self._rbottom_ain0)
            ratio_ain1 = self._rbottom_ain1 / (self._rtop_ain1 + self._rbottom_ain1)

            return {
                "connected": True,
                "status": "Conectado (Simulado)",
                "firmware_version": self._firmware_version,
                "uptime_seconds": uptime,
                "ads1115_status": self._ads1115_status,
                "ads1115_i2c_address": self._ads1115_i2c_address,
                "ads1115_data_rate": self._ads1115_data_rate,
                "vs_mpx_mv": self._VS_MPX_BASE,
                "calibration_origin": self._calibration_origin,
                "gain": round(self._gain, 6),
                "offset": round(self._offset, 6),
                "rtop_ain0": round(self._rtop_ain0, 2),
                "rbottom_ain0": round(self._rbottom_ain0, 2),
                "ratio_ain0": round(ratio_ain0, 6),
                "rtop_ain1": round(self._rtop_ain1, 2),
                "rbottom_ain1": round(self._rbottom_ain1, 2),
                "ratio_ain1": round(ratio_ain1, 6),
                "ocs3f_frames_ok": self._ocs3f_frames_ok,
                "ocs3f_frames_error": self._ocs3f_frames_error,
                "is_simulated": True,
            }

    def update_config(self, new_config: dict[str, Any]) -> dict[str, Any]:
        """Validate and update simulated device configuration in memory."""
        with self._lock:
            new_gain = self._gain
            new_offset = self._offset
            new_rtop_ain0 = self._rtop_ain0
            new_rbottom_ain0 = self._rbottom_ain0
            new_rtop_ain1 = self._rtop_ain1
            new_rbottom_ain1 = self._rbottom_ain1

            if "gain" in new_config:
                try:
                    gain_val = float(new_config["gain"])
                    if not (0.10 < gain_val < 10.0):
                        raise ValueError("GAIN debe estar estrictamente entre 0.10 y 10.0")
                    new_gain = gain_val
                except (TypeError, ValueError) as err:
                    raise ValueError(f"GAIN inválido: {err}")

            if "offset" in new_config:
                try:
                    offset_val = float(new_config["offset"])
                    if not (-500.0 < offset_val < 500.0):
                        raise ValueError("OFFSET debe estar estrictamente entre -500.0 y 500.0 kPa")
                    new_offset = offset_val
                except (TypeError, ValueError) as err:
                    raise ValueError(f"OFFSET inválido: {err}")

            resistors = [
                ("rtop_ain0", "Rtop AIN0"),
                ("rbottom_ain0", "Rbottom AIN0"),
                ("rtop_ain1", "Rtop AIN1"),
                ("rbottom_ain1", "Rbottom AIN1"),
            ]
            temp_res = {
                "rtop_ain0": new_rtop_ain0,
                "rbottom_ain0": new_rbottom_ain0,
                "rtop_ain1": new_rtop_ain1,
                "rbottom_ain1": new_rbottom_ain1,
            }

            for key, label in resistors:
                if key in new_config:
                    try:
                        r_val = float(new_config[key])
                        if not (100.0 <= r_val <= 1000000.0):
                            raise ValueError(f"{label} debe estar entre 100 Ω y 1,000,000 Ω")
                        temp_res[key] = r_val
                    except (TypeError, ValueError) as err:
                        raise ValueError(f"{label} inválido: {err}")

            ratio_ain0 = temp_res["rbottom_ain0"] / (temp_res["rtop_ain0"] + temp_res["rbottom_ain0"])
            ratio_ain1 = temp_res["rbottom_ain1"] / (temp_res["rtop_ain1"] + temp_res["rbottom_ain1"])

            if not (0.05 < ratio_ain0 < 0.95):
                raise ValueError(f"Ratio AIN0 calculado ({ratio_ain0:.4f}) debe estar estrictamente entre 0.05 y 0.95")
            if not (0.05 < ratio_ain1 < 0.95):
                raise ValueError(f"Ratio AIN1 calculado ({ratio_ain1:.4f}) debe estar estrictamente entre 0.05 y 0.95")

            self._gain = new_gain
            self._offset = new_offset
            self._rtop_ain0 = temp_res["rtop_ain0"]
            self._rbottom_ain0 = temp_res["rbottom_ain0"]
            self._rtop_ain1 = temp_res["rtop_ain1"]
            self._rbottom_ain1 = temp_res["rbottom_ain1"]
            self._calibration_origin = "Simulado (Modificado en memoria)"

        return self.get_device_info()


class Esp32WebSocketClient:
    """Real WebSocket client implementing Protocol v1 (docs/websocket_protocol.md)."""

    def __init__(self, url: str = DEFAULT_WS_URL, auto_reconnect: bool = True) -> None:
        self.url = url
        self.auto_reconnect = auto_reconnect
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._lock = threading.Lock()
        self._req_counter = 0

        self._latest_telemetry: dict[str, Any] | None = None
        self._telemetry_callback: Callable[[dict], None] | None = None
        self._pending_requests: dict[str, dict[str, Any]] = {}

        # Cached device info & calibration
        self._device_info_cache: dict[str, Any] = {}
        self._calibration_cache: dict[str, Any] = {
            "gain": 1.026770,
            "offset_kpa": -3.388341,
            "rtop_ain0_ohm": 32700.0,
            "rbottom_ain0_ohm": 21800.0,
            "rtop_ain1_ohm": 33300.0,
            "rbottom_ain1_ohm": 21500.0,
            "ratio_ain0": 0.400000,
            "ratio_ain1": 0.392336,
        }

    def set_telemetry_callback(self, callback: Callable[[dict], None]) -> None:
        """Register a callback to receive parsed telemetry samples."""
        with self._lock:
            self._telemetry_callback = callback

    def is_connected(self) -> bool:
        """Returns True only after successful hello / hello_ack handshake."""
        with self._lock:
            return self._connected

    def start(self) -> None:
        """Start the background WebSocket reconnection thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the background WebSocket thread."""
        with self._lock:
            self._running = False
            self._connected = False
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass

    def _next_request_id(self) -> str:
        with self._lock:
            self._req_counter += 1
            return f"req-{self._req_counter:03d}"

    def _run_loop(self) -> None:
        """Background thread running connection and reconnection attempts."""
        while self._running:
            try:
                self._connect_and_listen()
            except Exception:
                pass

            with self._lock:
                self._connected = False
                self._fail_pending_requests("Conexión WebSocket perdida")

            if not self.auto_reconnect or not self._running:
                break

            time.sleep(1.0)

    def _connect_and_listen(self) -> None:
        """Single connection session using websocket-client."""
        if websocket is None:
            raise RuntimeError("El paquete websocket-client no está instalado")

        ws = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        with self._lock:
            self._ws = ws

        ws.run_forever(ping_interval=10, ping_timeout=5)

    def _on_open(self, ws: Any) -> None:
        """Send hello handshake immediately upon socket open."""
        req_id = self._next_request_id()
        msg = {
            "type": "hello",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": req_id,
            "client": "monitor-o2-flask",
        }
        ws.send(json.dumps(msg))

    def _on_message(self, ws: Any, message: str) -> None:
        """Process incoming JSON messages from ESP32."""
        try:
            data = json.loads(message)
        except Exception:
            return

        msg_type = data.get("type")
        req_id = data.get("request_id")

        if msg_type == "hello_ack":
            with self._lock:
                self._connected = True
                self._device_info_cache["firmware_version"] = data.get("firmware_version", "0.1.0")
                self._device_info_cache["uptime_ms"] = data.get("uptime_ms", 0)

        elif msg_type == "telemetry":
            sample = self._parse_telemetry_frame(data)
            with self._lock:
                self._latest_telemetry = sample
                cb = self._telemetry_callback

            if cb:
                try:
                    cb(sample)
                except Exception:
                    pass

        # Resolve pending command requests if request_id matches
        if req_id and req_id in self._pending_requests:
            with self._lock:
                entry = self._pending_requests.get(req_id)
                if entry:
                    if msg_type == "error":
                        entry["err"] = data
                    else:
                        entry["res"] = data
                        if msg_type == "device_info":
                            self._device_info_cache.update(data)
                        elif msg_type == "calibration" or (msg_type == "ack" and "calibration" in data):
                            calib_data = data.get("calibration", data)
                            self._calibration_cache.update(calib_data)

                    entry["evt"].set()

    def _on_error(self, ws: Any, error: Any) -> None:
        """Handle socket errors."""
        with self._lock:
            self._connected = False

    def _on_close(self, ws: Any, close_status_code: Any, close_msg: Any) -> None:
        """Handle socket closure."""
        with self._lock:
            self._connected = False

    def _parse_telemetry_frame(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Convert a WebSocket telemetry frame to internal sample format."""
        vs_mpx = float(frame.get("vs_mpx_v", 5.0218)) * 1000.0 if "vs_mpx_v" in frame else float(frame.get("vs_mpx_mv", 5020.0))

        return {
            "ts": round(time.time(), 3),
            "connected": True,
            "o2_pct": round(float(frame.get("o2_pct", 20.9)), 3),
            "flow_lpm": round(max(float(frame.get("flow_l_min", 0.0)), 0.0), 3),
            "temp_c": round(float(frame.get("temperature_c", 25.0)), 3),
            "p_nominal_kpa": round(float(frame.get("p_nominal_kpa", 101.3)), 4),
            "p_calibrated_kpa": round(float(frame.get("p_calibrated_kpa", 101.3)), 4),
            "p_ema_kpa": round(float(frame.get("p_ema_kpa", 101.3)), 4),
            "ain0_mv": round(float(frame.get("ain0_mv", 1650.0)), 2),
            "vs_mpx_mv": round(vs_mpx, 2),
            "seq": frame.get("seq", 0),
            "uptime_ms": frame.get("uptime_ms", 0),
            "pressure_valid": frame.get("pressure_valid", True),
            "oxygen_valid": frame.get("oxygen_valid", True),
        }

    def _send_command(self, payload: dict[str, Any], timeout: float = 3.0) -> dict[str, Any]:
        """Send a JSON command over WebSocket and wait synchronously for response ACK."""
        req_id = payload.get("request_id") or self._next_request_id()
        payload["request_id"] = req_id
        payload["protocol_version"] = PROTOCOL_VERSION

        evt = threading.Event()
        entry = {"evt": evt, "res": None, "err": None}

        with self._lock:
            if not self._connected and self._ws is None:
                raise ConnectionError("No hay conexión con el ESP32 (WebSocket desconectado)")
            self._pending_requests[req_id] = entry
            ws = self._ws

        try:
            ws.send(json.dumps(payload))
        except Exception as err:
            with self._lock:
                self._pending_requests.pop(req_id, None)
            raise ConnectionError(f"Error al enviar comando por WebSocket: {err}")

        success = evt.wait(timeout=timeout)
        with self._lock:
            self._pending_requests.pop(req_id, None)

        if not success:
            raise TimeoutError(f"Timeout esperando respuesta para request_id={req_id}")

        if entry["err"]:
            err_obj = entry["err"]
            code = err_obj.get("code", "error")
            msg = err_obj.get("message", "Error reportado por ESP32")
            raise ValueError(f"{code}: {msg}")

        return entry["res"] or {}

    def _fail_pending_requests(self, reason: str) -> None:
        """Fail all pending request events when socket disconnects."""
        for req_id, entry in list(self._pending_requests.items()):
            entry["err"] = {"code": "connection_error", "message": reason}
            entry["evt"].set()
        self._pending_requests.clear()

    # ── Public Client Interface ─────────────────────────────────────────────

    def read(self) -> dict[str, Any]:
        """Return latest received telemetry sample or a fallback disconnected sample."""
        with self._lock:
            if self._latest_telemetry:
                return dict(self._latest_telemetry)

            return {
                "ts": round(time.time(), 3),
                "connected": self._connected,
                "o2_pct": 0.0,
                "flow_lpm": 0.0,
                "temp_c": 0.0,
                "p_nominal_kpa": 0.0,
                "p_calibrated_kpa": 0.0,
                "p_ema_kpa": 0.0,
                "ain0_mv": 0.0,
                "vs_mpx_mv": 0.0,
            }

    def ping(self) -> dict[str, Any]:
        """Send ping command."""
        return self._send_command({"type": "command", "command": "ping"})

    def set_telemetry_interval(self, interval_ms: int) -> dict[str, Any]:
        """Send set_telemetry_interval command."""
        return self._send_command({
            "type": "command",
            "command": "set_telemetry_interval",
            "interval_ms": interval_ms,
        })

    def get_info(self) -> dict[str, Any]:
        """Send get_info command."""
        return self._send_command({"type": "command", "command": "get_info"})

    def get_calibration(self) -> dict[str, Any]:
        """Send get_calibration command."""
        return self._send_command({"type": "command", "command": "get_calibration"})

    def set_calibration(self, calibration: dict[str, Any]) -> dict[str, Any]:
        """Send set_calibration command."""
        return self._send_command({
            "type": "command",
            "command": "set_calibration",
            "calibration": calibration,
        })

    def get_device_info(self) -> dict[str, Any]:
        """Return full device status, hardware parameters, and calibration config."""
        with self._lock:
            connected = self._connected
            info = dict(self._device_info_cache)
            calib = dict(self._calibration_cache)

        if connected:
            try:
                info_resp = self.get_info()
                info.update(info_resp)
            except Exception:
                pass

            try:
                calib_resp = self.get_calibration()
                calib.update(calib_resp.get("calibration", calib_resp))
            except Exception:
                pass

        rtop0 = calib.get("rtop_ain0_ohm", 32700.0)
        rbottom0 = calib.get("rbottom_ain0_ohm", 21800.0)
        ratio0 = calib.get("ratio_ain0", rbottom0 / (rtop0 + rbottom0))

        rtop1 = calib.get("rtop_ain1_ohm", 33300.0)
        rbottom1 = calib.get("rbottom_ain1_ohm", 21500.0)
        ratio1 = calib.get("ratio_ain1", rbottom1 / (rtop1 + rbottom1))

        return {
            "connected": connected,
            "status": "Conectado (WebSocket)" if connected else "Desconectado",
            "firmware_version": info.get("firmware_version", "0.1.0"),
            "uptime_seconds": int(info.get("uptime_ms", 0) / 1000),
            "ads1115_status": "OK" if info.get("ads1115_available", True) else "ERROR",
            "ads1115_i2c_address": info.get("ads1115_address", "0x48"),
            "ads1115_data_rate": f"{info.get('ads1115_rate_sps', 128)} SPS",
            "vs_mpx_mv": round(info.get("vs_mpx_v", 5.0218) * 1000.0, 2),
            "calibration_origin": calib.get("origin", "NVS"),
            "gain": round(calib.get("gain", 1.026770), 6),
            "offset": round(calib.get("offset_kpa", calib.get("offset", -3.388341)), 6),
            "rtop_ain0": round(rtop0, 2),
            "rbottom_ain0": round(rbottom0, 2),
            "ratio_ain0": round(ratio0, 6),
            "rtop_ain1": round(rtop1, 2),
            "rbottom_ain1": round(rbottom1, 2),
            "ratio_ain1": round(ratio1, 6),
            "ocs3f_frames_ok": info.get("ocs_frames_ok", 0),
            "ocs3f_frames_error": info.get("ocs_frames_error", 0),
            "is_simulated": False,
        }

    def update_config(self, new_config: dict[str, Any]) -> dict[str, Any]:
        """Validate and update ESP32 configuration via set_calibration command."""
        gain = float(new_config.get("gain", self._calibration_cache.get("gain", 1.026770)))
        offset = float(new_config.get("offset", self._calibration_cache.get("offset_kpa", -3.388341)))
        rtop0 = float(new_config.get("rtop_ain0", self._calibration_cache.get("rtop_ain0_ohm", 32700.0)))
        rbottom0 = float(new_config.get("rbottom_ain0", self._calibration_cache.get("rbottom_ain0_ohm", 21800.0)))
        rtop1 = float(new_config.get("rtop_ain1", self._calibration_cache.get("rtop_ain1_ohm", 33300.0)))
        rbottom1 = float(new_config.get("rbottom_ain1", self._calibration_cache.get("rbottom_ain1_ohm", 21500.0)))

        # Validation rules matching firmware
        if not (0.10 < gain < 10.0):
            raise ValueError("GAIN debe estar strictly entre 0.10 y 10.0")
        if not (-500.0 < offset < 500.0):
            raise ValueError("OFFSET debe estar estrictamente entre -500.0 y 500.0 kPa")
        for val, name in [(rtop0, "Rtop AIN0"), (rbottom0, "Rbottom AIN0"), (rtop1, "Rtop AIN1"), (rbottom1, "Rbottom AIN1")]:
            if not (100.0 <= val <= 1000000.0):
                raise ValueError(f"{name} debe estar entre 100 Ω y 1,000,000 Ω")

        ratio0 = rbottom0 / (rtop0 + rbottom0)
        ratio1 = rbottom1 / (rtop1 + rbottom1)
        if not (0.05 < ratio0 < 0.95):
            raise ValueError(f"Ratio AIN0 calculado ({ratio0:.4f}) debe estar estrictamente entre 0.05 y 0.95")
        if not (0.05 < ratio1 < 0.95):
            raise ValueError(f"Ratio AIN1 calculado ({ratio1:.4f}) debe estar estrictamente entre 0.05 y 0.95")

        calib_payload = {
            "gain": gain,
            "offset_kpa": offset,
            "rtop_ain0_ohm": rtop0,
            "rbottom_ain0_ohm": rbottom0,
            "rtop_ain1_ohm": rtop1,
            "rbottom_ain1_ohm": rbottom1,
        }

        self.set_calibration(calib_payload)
        return self.get_device_info()


# Module global state for client mode ("simulated" vs "websocket")
_client_mode = "simulated"
_simulated_instance = SimulatedEsp32Client()
_websocket_instance: Esp32WebSocketClient | None = None
_mode_lock = threading.Lock()


def set_client_mode(mode: str, url: str = DEFAULT_WS_URL) -> Any:
    """Set active client mode: 'simulated' or 'websocket'."""
    global _client_mode, _websocket_instance
    with _mode_lock:
        if mode not in ("simulated", "websocket"):
            raise ValueError(f"Modo inválido: '{mode}'. Opciones permitidas: 'simulated', 'websocket'")

        _client_mode = mode
        if mode == "websocket":
            if _websocket_instance is None or _websocket_instance.url != url:
                if _websocket_instance:
                    _websocket_instance.stop()
                _websocket_instance = Esp32WebSocketClient(url=url)
                _websocket_instance.start()
            return _websocket_instance
        else:
            if _websocket_instance:
                _websocket_instance.stop()
            return _simulated_instance


def get_client_mode() -> str:
    """Return current client mode ('simulated' or 'websocket')."""
    with _mode_lock:
        return _client_mode


def get_device_client() -> SimulatedEsp32Client | Esp32WebSocketClient:
    """Return the currently active ESP32 client instance."""
    with _mode_lock:
        if _client_mode == "websocket" and _websocket_instance is not None:
            return _websocket_instance
        return _simulated_instance
