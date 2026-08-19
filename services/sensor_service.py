"""
services/sensor_service.py — Arduino hardware serial reader.

Reads distance data from an Arduino UNO over USB serial.
The Arduino sketch should print lines in this format:
    Distance: 28.4 cm

Key features
------------
  • Automatic reconnection on disconnection (exponential backoff)
  • Robust regex parsing that handles malformed lines gracefully
  • Never crashes the Flask application — all errors are caught and logged
  • Feeds valid readings into analytics_service.process_reading()

This module is only active when APP_MODE=HARDWARE.
"""

import logging
import re
import time
import threading

import config
from services import analytics_service

log = logging.getLogger(__name__)

# Regex to extract the distance value from Arduino serial output.
# Matches: "Distance: 28.4 cm" or "distance:28.4cm" (case-insensitive)
_DISTANCE_RE = re.compile(
    r"distance\s*:\s*([-+]?\d+(?:\.\d+)?)\s*cm",
    re.IGNORECASE
)

# Reconnection settings
_INITIAL_RETRY_DELAY = 3.0   # seconds
_MAX_RETRY_DELAY     = 30.0  # seconds (exponential backoff cap)


def _extract_distance(line: str):
    """
    Parse a distance value from one line of Arduino serial output.

    Returns the distance as a float, or None if the line doesn't match.
    """
    match = _DISTANCE_RE.search(line)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _update_connection_status(connected: bool):
    """Update the sensor_status in the analytics latest dict."""
    from services.analytics_service import _latest, _lock
    with _lock:
        _latest["connected"]     = connected
        _latest["sensor_status"] = "HARDWARE" if connected else "DISCONNECTED"


def run():
    """
    Background thread: reads from the Arduino serial port indefinitely.

    On connection failure, waits and retries with exponential backoff.
    Never raises an unhandled exception.
    """
    try:
        import serial
        import serial.serialutil
    except ImportError:
        log.error(
            "pyserial is not installed. "
            "Run: pip install pyserial\n"
            "Or switch to MOCK mode by setting APP_MODE=MOCK in .env"
        )
        return

    retry_delay = _INITIAL_RETRY_DELAY

    while True:
        try:
            log.info(
                "Attempting to connect to Arduino on %s at %d baud...",
                config.SERIAL_PORT, config.BAUD_RATE
            )
            with serial.Serial(
                port=config.SERIAL_PORT,
                baudrate=config.BAUD_RATE,
                timeout=2.0
            ) as ser:
                log.info("Arduino connected on %s", config.SERIAL_PORT)
                _update_connection_status(True)
                retry_delay = _INITIAL_RETRY_DELAY   # reset backoff on success

                while True:
                    # Read one line from serial (blocks until newline or timeout)
                    raw = ser.readline()
                    try:
                        line = raw.decode("utf-8", errors="ignore").strip()
                    except Exception:
                        continue

                    if not line:
                        continue

                    log.debug("Serial line: %s", line)
                    distance = _extract_distance(line)

                    if distance is not None:
                        analytics_service.process_reading(distance, sensor_mode="HARDWARE")
                    else:
                        # Non-distance line (e.g. "Arduino ready", blank, etc.)
                        log.debug("Non-distance line ignored: %s", line)

        except Exception as exc:
            _update_connection_status(False)
            log.warning(
                "Serial connection failed (%s). Retrying in %.0f s...",
                exc, retry_delay
            )
            time.sleep(retry_delay)
            # Exponential backoff: double the delay, capped at MAX_RETRY_DELAY
            retry_delay = min(retry_delay * 2, _MAX_RETRY_DELAY)


def start_thread():
    """Launch the serial reader in a daemon background thread."""
    t = threading.Thread(target=run, daemon=True, name="HardwareSensor")
    t.start()
    return t
