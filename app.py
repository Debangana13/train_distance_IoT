"""
app.py — AI Train Distance Alert System — Flask Application Entry Point.

This file wires everything together:
  • Flask app and database initialisation
  • REST API route definitions
  • Background sensor thread startup (MOCK or HARDWARE)

Architecture:
  sensor (mock/hardware)
      → analytics_service.process_reading()
          → ai_service.predict()
          → models.database.save_reading()
  Flask routes → analytics_service.get_latest() / get_buffer()
              → models.database.get_history() / get_statistics()
"""

import csv
import io
import logging
import os

from flask import Flask, jsonify, render_template, request, Response

import config
from models.database import db, get_history, get_statistics
from services import analytics_service

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"]    = config.SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Ensure the data/ directory exists before SQLite tries to create the file
os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

# Bind the db object to this app
db.init_app(app)

# Give analytics_service a reference to the Flask app (needed for DB context)
analytics_service.init(app)

# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("index.html", app_mode=config.APP_MODE)


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------

@app.route("/api/current")
def api_current():
    """
    GET /api/current

    Returns the most recent processed sensor reading.
    Response schema:
        timestamp, distance, velocity, acceleration, risk_score,
        anomaly_score, status, trend, proximity_risk, velocity_risk,
        accel_risk, time_to_critical, mode, sensor_status
    """
    latest = analytics_service.get_latest()

    # Friendly time-to-critical label for the frontend
    ttc = latest.get("time_to_critical")
    if ttc is None:
        ttc_display = "Not approaching"
    elif ttc == 0.0:
        ttc_display = "CRITICAL NOW"
    else:
        ttc_display = f"{ttc:.1f} s"

    return jsonify({
        **latest,
        "time_to_critical_display": ttc_display,
    })


@app.route("/api/history")
def api_history():
    """
    GET /api/history?limit=100

    Returns recent readings from the database (newest first).
    Default limit: 100. Max limit: 500.
    """
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except (ValueError, TypeError):
        limit = 100

    with app.app_context():
        rows = get_history(limit)

    return jsonify(rows)


@app.route("/api/statistics")
def api_statistics():
    """
    GET /api/statistics

    Returns aggregate statistics over all stored database readings.
    """
    with app.app_context():
        stats = get_statistics()
    return jsonify(stats)


@app.route("/api/system-status")
def api_system_status():
    """
    GET /api/system-status

    Returns system health information for the dashboard health panel.
    """
    latest = analytics_service.get_latest()
    return jsonify({
        "app_mode":       config.APP_MODE,
        "sensor_status":  latest.get("sensor_status", "UNKNOWN"),
        "connected":      latest.get("connected", False),
        "ml_model":       "ACTIVE",
        "database":       "ACTIVE",
        "last_reading":   latest.get("timestamp"),
        "buffer_size":    len(analytics_service.get_buffer()),
        "critical_dist":  config.CRITICAL_DISTANCE,
        "warning_dist":   config.WARNING_DISTANCE,
    })


@app.route("/api/export/csv")
def api_export_csv():
    """
    GET /api/export/csv?limit=500

    Downloads the most recent readings as a CSV file.
    """
    try:
        limit = min(int(request.args.get("limit", 500)), 2000)
    except (ValueError, TypeError):
        limit = 500

    with app.app_context():
        rows = get_history(limit)

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "id", "timestamp", "distance_cm", "velocity_cms",
        "acceleration_cms2", "risk_score", "anomaly_score",
        "status", "sensor_mode"
    ])

    # Data rows (reversed so oldest first in the CSV)
    for row in reversed(rows):
        writer.writerow([
            row.get("id", ""),
            row.get("timestamp", ""),
            row.get("distance", ""),
            row.get("velocity", ""),
            row.get("acceleration", ""),
            row.get("risk_score", ""),
            row.get("anomaly_score", ""),
            row.get("status", ""),
            row.get("sensor_mode", ""),
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sensor_history.csv"},
    )


# ---------------------------------------------------------------------------
# Routes — Simulator Controls (MOCK mode only)
# ---------------------------------------------------------------------------

@app.route("/api/simulator/control", methods=["POST"])
def api_simulator_control():
    """
    POST /api/simulator/control

    Control the mock sensor simulator. Only effective when APP_MODE=MOCK.

    Request body (JSON):
        action   : "set_scenario" | "set_speed" | "set_distance" |
                   "pause" | "resume" | "reset"
        scenario : (for set_scenario) scenario name string
        speed    : (for set_speed) float multiplier 0.1–5.0
        distance : (for set_distance) float cm
    """
    if not config.IS_MOCK:
        return jsonify({"error": "Simulator controls only available in MOCK mode"}), 400

    from services import mock_sensor
    data   = request.get_json(silent=True) or {}
    action = data.get("action", "")

    if action == "set_scenario":
        mock_sensor.set_scenario(data.get("scenario", "random_demo"))
    elif action == "set_speed":
        mock_sensor.set_speed_multiplier(data.get("speed", 1.0))
    elif action == "set_distance":
        mock_sensor.set_starting_distance(data.get("distance", 100.0))
    elif action == "pause":
        mock_sensor.pause()
    elif action == "resume":
        mock_sensor.resume()
    elif action == "reset":
        mock_sensor.reset()
    else:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    return jsonify({"ok": True, "state": mock_sensor.get_state()})


@app.route("/api/simulator/state")
def api_simulator_state():
    """GET /api/simulator/state — current simulator control state."""
    if not config.IS_MOCK:
        return jsonify({"error": "Not in MOCK mode"}), 400
    from services import mock_sensor
    return jsonify(mock_sensor.get_state())


# ---------------------------------------------------------------------------
# Application startup
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Initialise database tables
    with app.app_context():
        db.create_all()
        log.info("Database initialised at %s", config.DB_PATH)

    # Start the appropriate sensor backend
    if config.IS_MOCK:
        log.info("Starting in MOCK mode — Arduino not required.")
        from services import mock_sensor
        mock_sensor.start_thread()
    else:
        log.info(
            "Starting in HARDWARE mode — connecting to %s at %d baud.",
            config.SERIAL_PORT, config.BAUD_RATE
        )
        from services import sensor_service
        sensor_service.start_thread()

    log.info(
        "Dashboard available at http://127.0.0.1:%d",
        config.FLASK_PORT
    )
    app.run(
        host="0.0.0.0",
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        use_reloader=False,   # prevents double-starting background threads
    )
