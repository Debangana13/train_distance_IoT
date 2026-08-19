"""
services/analytics_service.py — Feature engineering and reading pipeline.

This module is the central hub that connects the raw sensor reading
(a single distance value in cm) to the full processed result that
gets stored in the database and sent to the dashboard.

Pipeline for every incoming reading:
  raw distance
      → compute velocity (cm/s from real elapsed time)
      → compute acceleration (cm/s²)
      → compute moving average (last MA_WINDOW readings)
      → AI risk analysis (ai_service.py)
      → assemble full reading dict
      → update in-memory buffer (for API responses)
      → write to SQLite database (with duplicate suppression)
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

import config
from services.ai_service import AIRiskEngine

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level shared state
# ---------------------------------------------------------------------------

# Thread lock protects all shared state from concurrent access
_lock = threading.Lock()

# Ring buffer of the last BUFFER_SIZE processed readings (in-memory)
_buffer: deque = deque(maxlen=config.BUFFER_SIZE)

# The most recent fully processed reading (served by GET /api/current)
_latest: dict = {
    "timestamp":       None,
    "distance":        None,
    "velocity":        0.0,
    "acceleration":    0.0,
    "risk_score":      0.0,
    "anomaly_score":   0.0,
    "status":          "WAITING",
    "trend":           "STABLE",
    "proximity_risk":  0.0,
    "velocity_risk":   0.0,
    "accel_risk":      0.0,
    "time_to_critical": None,
    "mode":            config.APP_MODE,
    "sensor_status":   "INITIALISING",
    "connected":       False,
}

# Shared AI engine (one instance, reused for all readings)
_ai_engine = AIRiskEngine()

# Track timing for velocity calculation (uses real wall-clock time)
_last_distance: float = None
_last_time: float     = None

# Track previous velocity for acceleration calculation
_last_velocity: float = 0.0

# Short window for moving average calculation
_ma_window: deque = deque(maxlen=config.MA_WINDOW)

# Track last DB write time for duplicate suppression
_last_db_write_time: float = 0.0

# Flask app reference (set by app.py during startup)
_flask_app = None


def init(flask_app):
    """Store a reference to the Flask app so we can use app context for DB writes."""
    global _flask_app
    _flask_app = flask_app


# ---------------------------------------------------------------------------
# Main processing function
# ---------------------------------------------------------------------------

def process_reading(raw_distance: float, sensor_mode: str = None):
    """
    Process a single raw distance reading through the full analytics pipeline.

    This is called by both mock_sensor.py and sensor_service.py.
    It is thread-safe (protected by _lock).

    Parameters
    ----------
    raw_distance  : Distance in centimetres from the sensor (or simulator)
    sensor_mode   : Override for mode label ("MOCK" or "HARDWARE")
    """
    global _last_distance, _last_time, _last_velocity
    global _last_db_write_time

    mode = sensor_mode or config.APP_MODE

    # Basic sanity check — reject obviously invalid readings
    if raw_distance is None or raw_distance < 0 or raw_distance > 500:
        log.warning("Rejected invalid reading: %s", raw_distance)
        return

    distance = round(raw_distance, 2)
    now = time.monotonic()
    now_utc = datetime.now(timezone.utc)

    with _lock:
        # --- Velocity (cm/s) ---
        # Velocity = change in distance / elapsed time
        # Negative velocity means the object is APPROACHING the sensor.
        if _last_distance is not None and _last_time is not None:
            dt = now - _last_time
            if dt > 0.01:  # avoid division by near-zero
                velocity = (distance - _last_distance) / dt
            else:
                velocity = _last_velocity
        else:
            velocity = 0.0
        velocity = round(velocity, 3)

        # --- Acceleration (cm/s²) ---
        # Acceleration = change in velocity / elapsed time
        if _last_time is not None:
            dt = now - _last_time
            if dt > 0.01:
                acceleration = (velocity - _last_velocity) / dt
            else:
                acceleration = 0.0
        else:
            acceleration = 0.0
        acceleration = round(acceleration, 3)

        # --- Moving average ---
        _ma_window.append(distance)
        moving_avg = sum(_ma_window) / len(_ma_window)

        # --- Update tracking state ---
        prev_distance  = _last_distance if _last_distance is not None else distance
        _last_distance = distance
        _last_time     = now
        _last_velocity = velocity

        # --- AI risk analysis ---
        ai_result = _ai_engine.predict(
            distance      = distance,
            prev_distance = prev_distance,
            velocity      = velocity,
            acceleration  = acceleration,
            moving_avg    = moving_avg,
        )

        # --- Assemble the full reading dict ---
        reading = {
            "timestamp":       now_utc.strftime("%Y-%m-%dT%H:%M:%S"),
            "distance":        distance,
            "velocity":        velocity,
            "acceleration":    acceleration,
            "moving_avg":      round(moving_avg, 2),
            "risk_score":      ai_result["risk_score"],
            "anomaly_score":   ai_result["anomaly_score"],
            "status":          ai_result["status"],
            "trend":           ai_result["trend"],
            "proximity_risk":  ai_result["proximity_risk"],
            "velocity_risk":   ai_result["velocity_risk"],
            "accel_risk":      ai_result["accel_risk"],
            "time_to_critical": ai_result["time_to_critical"],
            "mode":            mode,
            "sensor_status":   "SIMULATED" if mode == "MOCK" else "HARDWARE",
            "connected":       True,
        }

        # --- Update in-memory buffer and latest pointer ---
        _buffer.append(reading)
        _latest.update(reading)

    # --- Database write (with duplicate suppression) ---
    # Only write if enough time has elapsed since the last write.
    # This prevents flooding the DB with near-identical readings.
    elapsed_since_write = now - _last_db_write_time
    if elapsed_since_write >= config.SAMPLE_INTERVAL:
        _last_db_write_time = now
        _write_to_db(reading)


def _write_to_db(reading: dict):
    """Write a reading to SQLite (must have Flask app context)."""
    if _flask_app is None:
        return
    try:
        from models.database import save_reading
        save_reading(_flask_app, reading)
    except Exception as exc:
        log.error("DB write failed: %s", exc)


# ---------------------------------------------------------------------------
# Accessors (called by Flask route handlers)
# ---------------------------------------------------------------------------

def get_latest() -> dict:
    """Return the most recent processed reading."""
    with _lock:
        return dict(_latest)


def get_buffer() -> list:
    """Return the in-memory ring buffer as a list (newest last)."""
    with _lock:
        return list(_buffer)
