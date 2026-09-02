"""Calibration history service — Phase 8 (Audited & Implemented).

Provides SQLite persistence for completed calibration sessions and their 7 measurement points using standard library sqlite3.
DB path is configurable via CALIBRATION_DB_PATH or Flask app.config.
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
from typing import Any, Optional

DEFAULT_DB_PATH = "data/calibration_history.sqlite3"


class CalibrationHistoryService:
    """Independent SQLite manager for calibration session history."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get("CALIBRATION_DB_PATH", DEFAULT_DB_PATH)
        self._init_db()

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_connection(self) -> sqlite3.Connection:
        """Create connection ensuring parent directory exists."""
        parent_dir = os.path.dirname(os.path.abspath(self._db_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS calibration_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    saved_at TEXT NOT NULL,
                    firmware_version TEXT,
                    gain REAL NOT NULL,
                    offset_kpa REAL NOT NULL,
                    r_squared REAL NOT NULL,
                    max_error_kpa REAL NOT NULL,
                    mean_absolute_error_kpa REAL NOT NULL,
                    repeatability_kpa REAL NOT NULL
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS calibration_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    target_mmhg REAL NOT NULL,
                    target_kpa REAL NOT NULL,
                    observed_mmhg REAL NOT NULL,
                    observed_kpa REAL NOT NULL,
                    sample_count INTEGER NOT NULL,
                    mean_p_nominal_kpa REAL NOT NULL,
                    std_p_nominal_kpa REAL NOT NULL,
                    min_p_nominal_kpa REAL NOT NULL,
                    max_p_nominal_kpa REAL NOT NULL,
                    residual_kpa REAL,
                    samples TEXT NOT NULL,
                    sample_timestamps TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES calibration_sessions(session_id) ON DELETE CASCADE
                );
            """)

            conn.commit()

    def save_session(self, session_state: dict[str, Any], firmware_version: str | None = None) -> dict[str, Any]:
        """Save a completed calibration session and its measurement points to SQLite.

        Idempotent: if session_id already exists in the database, returns the existing record.
        """
        session_id = session_state.get("session_id")
        if not session_id:
            raise ValueError("La sesión de calibración debe contener un session_id válido.")

        # Idempotency check: if session already exists, return existing details without error
        existing = self.get_session_detail(session_id)
        if existing is not None:
            return existing

        results = session_state.get("results")
        if not results:
            raise ValueError("No se pueden guardar sesiones sin resultados de calibración válidos.")

        saved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        created_at = session_state.get("created_at") or saved_at

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")

            cursor.execute(
                """
                INSERT OR IGNORE INTO calibration_sessions (
                    session_id, created_at, saved_at, firmware_version,
                    gain, offset_kpa, r_squared, max_error_kpa,
                    mean_absolute_error_kpa, repeatability_kpa
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    created_at,
                    saved_at,
                    firmware_version,
                    float(results["gain"]),
                    float(results["offset"]),
                    float(results["r_squared"]),
                    float(results["max_error"]),
                    float(results["mean_absolute_error"]),
                    float(results["repeatability"]),
                ),
            )

            # Insert points if session was inserted
            if cursor.rowcount > 0:
                points = session_state.get("points", [])
                residuals = results.get("residuals", [])

                for idx, pt in enumerate(points):
                    stats = pt.get("stats", {})
                    samples_list = pt.get("samples", [])
                    ts_list = pt.get("sample_timestamps", [])

                    residual_val = float(residuals[idx]) if idx < len(residuals) else None

                    cursor.execute(
                        """
                        INSERT INTO calibration_points (
                            session_id, step_index, target_mmhg, target_kpa,
                            observed_mmhg, observed_kpa, sample_count,
                            mean_p_nominal_kpa, std_p_nominal_kpa, min_p_nominal_kpa,
                            max_p_nominal_kpa, residual_kpa, samples, sample_timestamps
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            int(pt.get("step_index", idx)),
                            float(pt["target_mmhg"]),
                            float(pt["target_kpa"]),
                            float(pt["observed_mmhg"]),
                            float(pt["observed_kpa"]),
                            int(stats.get("count", len(samples_list))),
                            float(stats.get("mean", 0.0)),
                            float(stats.get("std", 0.0)),
                            float(stats.get("min", 0.0)),
                            float(stats.get("max", 0.0)),
                            residual_val,
                            json.dumps(samples_list),
                            json.dumps(ts_list),
                        ),
                    )

            conn.commit()

        detail = self.get_session_detail(session_id)
        if detail is None:
            raise RuntimeError(f"Error al recuperar la sesión recién guardada '{session_id}'.")
        return detail

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved calibration sessions ordered by saved_at DESC (excluding raw samples)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT session_id, created_at, saved_at, firmware_version,
                       gain, offset_kpa, r_squared, max_error_kpa,
                       mean_absolute_error_kpa, repeatability_kpa
                FROM calibration_sessions
                ORDER BY saved_at DESC
                """
            ).fetchall()

            return [dict(row) for row in rows]

    def get_session_detail(self, session_id: str) -> Optional[dict[str, Any]]:
        """Retrieve full session detail including metadata, summary results, and all 7 points with raw samples."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            session_row = cursor.execute(
                """
                SELECT session_id, created_at, saved_at, firmware_version,
                       gain, offset_kpa, r_squared, max_error_kpa,
                       mean_absolute_error_kpa, repeatability_kpa
                FROM calibration_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

            if session_row is None:
                return None

            session_dict = dict(session_row)

            point_rows = cursor.execute(
                """
                SELECT step_index, target_mmhg, target_kpa, observed_mmhg, observed_kpa,
                       sample_count, mean_p_nominal_kpa, std_p_nominal_kpa, min_p_nominal_kpa,
                       max_p_nominal_kpa, residual_kpa, samples, sample_timestamps
                FROM calibration_points
                WHERE session_id = ?
                ORDER BY step_index ASC
                """,
                (session_id,),
            ).fetchall()

            points = []
            for row in point_rows:
                pt_dict = dict(row)
                pt_dict["samples"] = json.loads(pt_dict["samples"])
                pt_dict["sample_timestamps"] = json.loads(pt_dict["sample_timestamps"])
                points.append(pt_dict)

            session_dict["points"] = points
            return session_dict


_history_service_instance: CalibrationHistoryService | None = None


def get_history_service(db_path: str | None = None) -> CalibrationHistoryService:
    """Return singleton instance of CalibrationHistoryService."""
    global _history_service_instance
    if _history_service_instance is None or db_path is not None:
        _history_service_instance = CalibrationHistoryService(db_path=db_path)
    return _history_service_instance
