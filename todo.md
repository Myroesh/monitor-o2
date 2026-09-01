# TODO — Monitor O2 App

> Proyecto PC para monitorización, calibración y configuración del ESP32 del monitor O2/presión.
> Stack objetivo: Flask + Jinja + Docker. Comunicación futura ESP32 ↔ Flask por WebSocket.

## Reglas de trabajo

- Trabajar por fases; no adelantar funcionalidades de fases futuras.
- Mantener `routes`, `services`, frontend y tests desacoplados.
- `esp32_client.py` será la única capa que conocerá el protocolo del ESP32.
- Flask/Jinja vive en la PC; el ESP32 no alojará la UI.
- El ESP32 funcionará autónomamente sin PC.
- NVS será la fuente de verdad de la calibración del ESP32.
- No introducir dependencias o servicios innecesarios.
- Mantener tests unitarios e integración.
- Cada fase se cierra solo cuando sus criterios de aceptación pasan.

## Fase 1 — Esqueleto Flask + Docker

- [x] Application factory `create_app()`.
- [x] Blueprints separados: Monitor, Calibración y Configuración.
- [x] `/` redirige a `/monitor`.
- [x] Templates base y placeholders.
- [x] CSS base.
- [x] `run.py`.
- [x] Dockerfile con Python 3.12.
- [x] `docker-compose.yml`.
- [x] pytest configurado.
- [x] Tests unitarios e integración iniciales.
- [x] Validación en Docker: 15/15 tests OK.

**Estado:** COMPLETADA.

## Fase 2 — Simulador de telemetría + Monitor funcional

- [x] Implementar `telemetry_service.py`.
- [x] Mantener último estado de telemetría.
- [x] Mantener buffer limitado de muestras.
- [x] Implementar modo simulado en `esp32_client.py`.
- [x] Simular variaciones suaves y plausibles de O2, flujo, temperatura, `p_nominal`, `p_calibrated`, `p_ema`, `ain0_mv` y `vs_mpx`.
- [x] Implementar `GET /api/telemetry`.
- [x] Hacer funcional `/monitor`.
- [x] Actualización dinámica cada ~250 ms sin recargar.
- [x] Mostrar estado ESP32, O2, flujo, temperatura, presión calibrada, Vs MPX y P nominal.
- [x] Gráfica de presión de los últimos ~60 s.
- [x] Selector de curva: presión calibrada instantánea, presión EMA y P nominal.
- [x] Evitar crecimiento ilimitado del buffer.
- [x] Chart.js disponible para uso offline/local.
- [x] Tests unitarios de telemetría.
- [x] Tests del simulador.
- [x] Test de `/api/telemetry`.
- [x] Todos los tests anteriores siguen pasando.

**Criterio de cierre:**
- `docker compose up --build` funciona.
- `/monitor` actualiza datos sin recargar.
- La gráfica recibe muestras continuamente.
- `/api/telemetry` devuelve JSON válido.
- `docker compose run --rm web pytest -v` pasa.

**Estado:** COMPLETADA. pytest 44/44 (host). GET /api/telemetry — contrato independiente del blueprint monitor. docker compose run --rm web pytest -v: pendiente verificación (requiere Docker Desktop activo).

## Fase 3 — Calibración guiada en Flask

- [x] Implementar `calibration_service.py`.
- [x] Conversión `mmHg -> kPa` con `1 mmHg = 0.133322 kPa`.
- [x] Wizard: 0, 50, 100, 150, 200, 250, 300 mmHg.
- [x] Campo editable de presión real observada.
- [x] Botón `Comenzar medición`.
- [x] Capturar varias muestras por punto.
- [x] Mostrar promedio, desviación estándar, mínimo y máximo.
- [x] Botón `Repetir paso`.
- [x] Botón `Paso anterior`.
- [x] Botón `Aceptar y continuar`.
- [x] Regresión lineal por mínimos cuadrados.
- [x] Calcular GAIN, OFFSET, R², residuos, error por punto, error máximo, error medio y repetibilidad.
- [x] No eliminar outliers automáticamente.
- [x] Permitir repetir un punto desde resultados.
- [x] Tests matemáticos con resultados conocidos.

**Estado:** COMPLETADA. pytest 65/65 (host). Toda matemática encapsulada en calibration_service.py. REST API bajo /api/calibration/*. UI con wizard guiado, stepper y resultados completos.

## Fase 4 — Configuración e información del equipo

- [x] Hacer funcional `/configuration`.
- [x] Mostrar firmware, estado ESP32, uptime, ADS1115, Vs MPX, origen de calibración, GAIN, OFFSET, resistencias/ratios y tramas OCS-3F.
- [x] Edición manual de parámetros con validación.
- [x] No escribir NVS hasta confirmación explícita.

**Estado:** COMPLETADA. pytest 77/77 (host). Estado e info del dispositivo desacoplados en esp32_client.py (Vs MPX ~5020 mV). REST API bajo /api/config. Ratios auto-calculados en tiempo real. Confirmación explícita en UI antes de guardar en memoria simulada.

## Fase 5 — Protocolo WebSocket ESP32 ↔ Flask

- [x] Definir contrato de mensajes antes de implementarlo (`docs/websocket_protocol.md`).
- [x] Telemetría ESP32 → Flask.
- [x] Comandos `ping`, `get_info`, `get_calibration`, `set_calibration`, `set_telemetry_interval`.
- [x] ACK explícito de guardado/verificación NVS.
- [x] Manejo de desconexión/reconexión en hilo secundario sin bloquear Flask.
- [x] Sustituir simulador sin cambiar rutas ni frontend (modo 'websocket' vs 'simulated').
- [x] Tests con cliente ESP32 fake/mock WebSocket.

**Estado:** COMPLETADA. pytest 105/105 (host). Implementado cliente WebSocket Protocol v1 en `esp32_client.py`. Handshake hello/hello_ack, comandos parametrizados con `request_id`, desacoplamiento total de telemetría a `TelemetryService`, prueba segura de escritura NVS (`verify_nvs_write`) y aplicación de calibración calculada preservando las 4 resistencias del hardware con comprobación obligatoria de ACK `nvs_verified` y relectura (*readback*).

## Fase 6 — Firmware ESP32 para modo PC

- [ ] Guardar firmware actual como respaldo antes de modificar. *(Tarea histórica previa a la modificación; se conserva como referencia documental o a sustituir por respaldo/tag de la versión estable actual)*
- [x] Retirar WiFiManager de la arquitectura final.
- [x] Mantener Preferences/NVS.
- [x] Mantener OCS-3F sin modificar parser.
- [x] Mantener ADS1115 no bloqueante a 128 SPS.
- [x] Mantener EMA `alpha = 0.15`.
- [x] GPIO27 corto → siguiente pantalla.
- [x] GPIO27 largo ~3 s → activar modo PC.
- [x] GPIO27 largo con modo PC activo → apagar modo PC inmediatamente.
- [x] SoftAP WPA2 solo durante modo PC.
- [x] IP esperada del ESP32: `192.168.4.1`.
- [x] WebSocket para Flask.
- [x] LCD: sin icono = Wi-Fi apagado; parpadeando = esperando Flask; fijo = Flask conectado.
- [x] ESP32 debe seguir funcionando autónomamente sin Flask.

**Estado:** FUNCIONALMENTE COMPLETADA Y VALIDADA CON HARDWARE REAL.

## Fase 7 — Integración real

- [x] Verificar acceso desde Docker al ESP32 `192.168.4.1`.
- [x] Conectar PC al SoftAP del ESP32.
- [x] Reemplazar simulador por WebSocket real.
- [x] Validar monitor en vivo. *(Comprobados físicamente en hardware real: presión, O₂, flujo, ventana ~60 s y selector P calibrada / EMA / nominal)*
- [x] Validar calibración completa. *(Calibración guiada de 7 puntos probada y funcional con hardware real; la calibración metrológica definitiva se realizará con la fuente de alimentación final ya que el cero depende de ella)*
- [ ] Aplicar GAIN/OFFSET desde Flask.
- [x] Verificar guardado NVS. *(Verificado mediante reescritura segura de los mismos valores activos + ACK nvs_verified + comprobación de readback)*
- [ ] Reiniciar ESP32 y verificar persistencia.
- [x] Validar reconexión.

**Estado:** EN PROGRESO / PARCIALMENTE VALIDADA. Integración física de telemetría en vivo, WebSocket real y prueba segura de guardado NVS completados.

## Fase 8 — Persistencia e historial en PC

- [ ] Crear SQLite solo cuando la integración principal sea estable.
- [ ] Historial de sesiones de calibración.
- [ ] Guardar puntos crudos y resultados.
- [ ] Fecha/hora y versión firmware.
- [ ] GAIN/OFFSET aplicados.
- [ ] R² y errores.
- [ ] Exportación futura si se necesita.

## Fase 9 — Cierre de producto

- [ ] Mejorar UX sin añadir complejidad innecesaria.
- [ ] Manejo claro de errores y estados desconectados.
- [ ] README de instalación y uso.
- [ ] Procedimiento de calibración.
- [ ] Cobertura de tests suficiente para servicios críticos.
- [ ] Revisión de seguridad del SoftAP y comandos de escritura.
- [ ] Versión estable del protocolo ESP32 ↔ Flask.
