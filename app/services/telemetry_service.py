"""Telemetry service — Phase 2, Phase 3 & Phase 5.

Maintains the last known state and a bounded history buffer of samples
received from the ESP32 client (real WebSocket or simulated).

Exposes a listener subscription interface so services (like calibration)
can consume new samples as they arrive over time without polling loops.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, Callable

from app.services.esp32_client import get_device_client

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
            except Exception:
                pass

        return sample

    def tick(self) -> dict:
        """Read one sample from the active client, store it, notify listeners and return it."""
        client = self._client()
        sample = client.read()
        return self.add_sample(sample)

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


def get_service() -> TelemetryService:
    """Return the application-level TelemetryService instance."""
    return _service
