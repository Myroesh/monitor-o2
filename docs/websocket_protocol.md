# WebSocket Protocol v1 — Monitor O2

## 1. Alcance

Contrato entre la aplicación Flask en la PC y el ESP32.

- Flask/Jinja vive en la PC.
- ESP32 actúa como servidor WebSocket.
- ESP32 funciona autónomamente sin PC.
- NVS sigue siendo la fuente de verdad de calibración.
- La calibración guiada se ejecuta en Flask; el ESP32 solo entrega telemetría y acepta parámetros finales.

## 2. Red y conexión

**Modo PC**
- Activación: pulsación larga GPIO27 (~3 s).
- Pulsación larga nuevamente: cierra inmediatamente modo PC.
- SoftAP SSID: `MonitorO2-ESP32`
- Contraseña prototipo: `12345678`
- IP ESP32: `192.168.4.1`
- WebSocket: `ws://192.168.4.1/ws`
- Máximo: **1 cliente WebSocket simultáneo**.

Estados:

```text
PC_MODE_OFF
   │ GPIO27 largo
   ▼
AP_WAITING
   │ handshake válido
   ▼
PC_CONNECTED
   │ GPIO27 largo
   ▼
PC_MODE_OFF
```

Si Flask se desconecta accidentalmente: `PC_CONNECTED -> AP_WAITING`.

LCD:
- sin icono = `PC_MODE_OFF`
- icono parpadeando = `AP_WAITING`
- icono fijo = `PC_CONNECTED`

## 3. Convenciones

- Formato: JSON UTF-8.
- `protocol_version`: `1`
- Comandos y respuestas usan `request_id`.
- Telemetría espontánea no necesita `request_id`.
- Unidades incluidas en nombres de campos.
- ESP32 usa `uptime_ms`; no requiere RTC.
- `seq` incrementa por paquete de telemetría.

## 4. Handshake

Flask -> ESP32:

```json
{
  "type": "hello",
  "protocol_version": 1,
  "request_id": "req-001",
  "client": "monitor-o2-flask"
}
```

ESP32 -> Flask:

```json
{
  "type": "hello_ack",
  "protocol_version": 1,
  "request_id": "req-001",
  "device": "MonitorO2",
  "firmware_version": "0.1.0",
  "uptime_ms": 18342
}
```

Solo después de `hello_ack` Flask considera al dispositivo conectado.

## 5. Telemetría

ESP32 -> Flask, default cada `200 ms` (5 Hz):

```json
{
  "type": "telemetry",
  "protocol_version": 1,
  "seq": 4182,
  "uptime_ms": 1234567,

  "o2_pct": 21.6,
  "flow_l_min": 0.2,
  "temperature_c": 24.5,

  "p_nominal_kpa": 3.38,
  "p_calibrated_kpa": 0.08,
  "p_ema_kpa": 0.08,

  "ain0_mv": 92.563,
  "vout_mpx_v": 0.23141,
  "ain1_mv": 1970.250,
  "vs_mpx_v": 5.0218,

  "pressure_valid": true,
  "oxygen_valid": true,

  "ocs_status1": 0,
  "ocs_status2": 0
}
```

Frecuencias permitidas inicialmente:
- 100 ms = 10 Hz
- 200 ms = 5 Hz (default)
- 250 ms = 4 Hz
- 500 ms = 2 Hz
- 1000 ms = 1 Hz

Cambiar telemetría NO modifica el muestreo interno del ADS1115.

## 6. Comandos

### ping

Flask -> ESP32:

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "req-010",
  "command": "ping"
}
```

Respuesta:

```json
{
  "type": "ack",
  "protocol_version": 1,
  "request_id": "req-010",
  "command": "ping",
  "uptime_ms": 1234567
}
```

### set_telemetry_interval

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "req-020",
  "command": "set_telemetry_interval",
  "interval_ms": 100
}
```

ACK:

```json
{
  "type": "ack",
  "protocol_version": 1,
  "request_id": "req-020",
  "command": "set_telemetry_interval",
  "interval_ms": 100
}
```

### get_info

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "req-030",
  "command": "get_info"
}
```

Respuesta:

```json
{
  "type": "device_info",
  "protocol_version": 1,
  "request_id": "req-030",
  "firmware_version": "0.1.0",
  "uptime_ms": 1234567,
  "ads1115_available": true,
  "ads1115_address": "0x48",
  "ads1115_rate_sps": 128,
  "vs_mpx_v": 5.0218,
  "ocs_frames_ok": 15423,
  "ocs_frames_error": 0,
  "calibration_origin": "NVS"
}
```

### get_calibration

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "req-040",
  "command": "get_calibration"
}
```

Respuesta:

```json
{
  "type": "calibration",
  "protocol_version": 1,
  "request_id": "req-040",
  "calibration_version": 2,
  "origin": "NVS",
  "gain": 1.026770,
  "offset_kpa": -3.388341,
  "rtop_ain0_ohm": 32700.0,
  "rbottom_ain0_ohm": 21800.0,
  "rtop_ain1_ohm": 33300.0,
  "rbottom_ain1_ohm": 21500.0,
  "ratio_ain0": 0.400000,
  "ratio_ain1": 0.392336
}
```

Los ratios son informativos y se calculan como:

`ratio = Rbottom / (Rtop + Rbottom)`

### set_calibration

La escritura es atómica: se envía la calibración completa.

```json
{
  "type": "command",
  "protocol_version": 1,
  "request_id": "req-050",
  "command": "set_calibration",
  "calibration": {
    "gain": 1.028542,
    "offset_kpa": -3.444140,
    "rtop_ain0_ohm": 32700.0,
    "rbottom_ain0_ohm": 21800.0,
    "rtop_ain1_ohm": 33300.0,
    "rbottom_ain1_ohm": 21500.0
  }
}
```

ESP32 debe:
1. parsear;
2. validar todos los parámetros;
3. aplicar temporalmente;
4. recalcular ratios;
5. guardar en NVS;
6. volver a leer/verificar NVS;
7. responder ACK solo si la verificación fue correcta.

ACK:

```json
{
  "type": "ack",
  "protocol_version": 1,
  "request_id": "req-050",
  "command": "set_calibration",
  "status": "nvs_verified",
  "calibration": {
    "gain": 1.028542,
    "offset_kpa": -3.444140,
    "rtop_ain0_ohm": 32700.0,
    "rbottom_ain0_ohm": 21800.0,
    "rtop_ain1_ohm": 33300.0,
    "rbottom_ain1_ohm": 21500.0,
    "ratio_ain0": 0.400000,
    "ratio_ain1": 0.392336
  }
}
```

Flask no debe mostrar “guardado correctamente” antes de recibir este ACK.

## 7. Errores

Formato único:

```json
{
  "type": "error",
  "protocol_version": 1,
  "request_id": "req-050",
  "code": "validation_error",
  "message": "PRESSURE_GAIN fuera de rango"
}
```

Códigos iniciales:
- `invalid_json`
- `unsupported_protocol`
- `unknown_command`
- `validation_error`
- `nvs_write_failed`
- `nvs_verify_failed`
- `not_ready`
- `client_limit_reached`
- `internal_error`

## 8. Reglas de calibración

No existen comandos `start_calibration` ni `capture_point`.

Flask:
1. recibe telemetría continua;
2. captura `p_nominal_kpa` durante la ventana definida;
3. calcula estadísticas/regresión;
4. al finalizar usa `set_calibration`.

Esto mantiene el procedimiento metrológico fuera del firmware.

## 9. Compatibilidad

Toda implementación v1 debe rechazar de forma explícita versiones de protocolo no soportadas.

Cambios incompatibles futuros requieren nueva `protocol_version`.
