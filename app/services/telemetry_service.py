"""Telemetry service — Phase 2, Phase 3 & Phase 5 (Audited).

Maintains the last known state and a bounded history buffer of samples
received from the ESP32 client (real WebSocket or simulated).

Exposes a listener subscription interface so services (like calibration)
can consume new samples as they arrive over time without polling loops.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Callable

from app.services.esp32_client import get_device_client, register_mode_change_listener

logger = logging.getLogger(__name__)

# Maximum samples kept in memory.
# At the nominal poll rate of 250 ms this holds ~75 s of data,
# giving the frontend a 15 s margin above the 60 s chart window.
BUFFER_MAX = 300


class TelemetryService:
    """Thread-safe telemetry store with a bounded sample buffer and listener events."""

    def __init__(self, client: Any | None = None, buffer_max: int = BUFFER_MAX) -> None:
        self._explicit_client = client
        self._lock = threading.Lock()
        self._buffer: deque[dict] = deque(maxlen=buffer_max)
        self._latest: dict | None = None
        self._listeners: list[Callable[[dict], None]] = []

    def _client(self) -> Any:
        return self._explicit_client if self._explicit_client is not None else get_device_client()

    def bind_active_client(self, client: Any | None = None) -> None:
        """Bind self.add_sample as telemetry callback to the active device client."""
        c = client if client is not None else self._client()
        if hasattr(c, "set_telemetry_callback"):
            c.set_telemetry_callback(self.add_sample)

    def is_simulated(self) -> bool:
        """Return True if active client is simulated."""
        return self._client().is_simulated()

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        """Register a callback function to be invoked when a new sample arrives."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        """Unregister a listener callback."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def add_sample(self, sample: dict) -> dict:
        """Add a telemetry sample to buffer and notify all registered listeners."""
        with self._lock:
            self._buffer.append(sample)
            self._latest = sample
            listeners = list(self._listeners)

        for callback in listeners:
            try:
                callback(sample)
            except Exception as err:
                logger.error("Error en listener de TelemetryService: %s", err, exc_info=True)

        return sample

    def tick(self) -> dict:
        """Read or retrieve current sample.

        In simulated mode: generates sample via client.read() and appends to buffer via add_sample().
        In websocket mode: telemetry frames are already pushed asynchronously to buffer via callback.
        Does NOT duplicate samples on tick() in websocket mode.
        """
        client = self._client()
        if client.is_simulated():
            sample = client.read()
            return self.add_sample(sample)
        else:
            latest = self.get_latest()
            if latest is not None:
                return latest
            return client.read()

    def get_latest(self) -> dict | None:
        """Return the most recent sample, or None if no data yet."""
        with self._lock:
            return self._latest

    def get_history(self) -> list[dict]:
        """Return a snapshot of the current buffer (oldest → newest)."""
        with self._lock:
            return list(self._buffer)

    def buffer_size(self) -> int:
        """Current number of samples in the buffer."""
        with self._lock:
            return len(self._buffer)


# Module-level singleton used by routes.
_service = TelemetryService()

# Automatically bind singleton to active client mode changes
register_mode_change_listener(lambda active_client: _service.bind_active_client(active_client))


def get_service() -> TelemetryService:
    """Return the application-level TelemetryService instance with bound client callback."""
    _service.bind_active_client()
    return _service
