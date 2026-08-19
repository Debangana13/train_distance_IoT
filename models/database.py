"""
models/database.py — SQLAlchemy database model and helper functions.

Stores every sensor reading with full feature set so you can analyse
historical data, plot trends, and demonstrate the AI pipeline working.
"""

import logging
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

log = logging.getLogger(__name__)

# The db object is created here and imported by app.py during initialisation.
db = SQLAlchemy()


class SensorReading(db.Model):
    """
    One row per processed sensor reading saved to SQLite.

    Fields
    ------
    id            : Auto-increment primary key
    timestamp     : UTC datetime when the reading was recorded
    distance      : Measured distance in cm
    velocity      : Rate of distance change (cm/s). Negative = approaching.
    acceleration  : Rate of velocity change (cm/s²)
    risk_score    : Combined AI risk 0–100
    anomaly_score : Isolation Forest anomaly component 0–1
    status        : NORMAL / CAUTION / WARNING / CRITICAL
    sensor_mode   : "MOCK" or "HARDWARE"
    """

    __tablename__ = "sensor_readings"

    id            = db.Column(db.Integer, primary_key=True)
    timestamp     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    distance      = db.Column(db.Float, nullable=False)
    velocity      = db.Column(db.Float, default=0.0)
    acceleration  = db.Column(db.Float, default=0.0)
    risk_score    = db.Column(db.Float, default=0.0)
    anomaly_score = db.Column(db.Float, default=0.0)
    status        = db.Column(db.String(20), default="NORMAL")
    sensor_mode   = db.Column(db.String(20), default="MOCK")

    def to_dict(self):
        """Return a JSON-serialisable dictionary."""
        return {
            "id":            self.id,
            "timestamp":     self.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
            "distance":      round(self.distance, 2),
            "velocity":      round(self.velocity, 2),
            "acceleration":  round(self.acceleration, 3),
            "risk_score":    round(self.risk_score, 1),
            "anomaly_score": round(self.anomaly_score, 3),
            "status":        self.status,
            "sensor_mode":   self.sensor_mode,
        }


# ---------------------------------------------------------------------------
# Helper functions used by analytics_service.py
# ---------------------------------------------------------------------------

def save_reading(app, reading_dict: dict):
    """
    Persist a processed reading dictionary to the database.
    Must be called with an active Flask app context.
    """
    try:
        with app.app_context():
            row = SensorReading(
                distance      = reading_dict["distance"],
                velocity      = reading_dict.get("velocity", 0.0),
                acceleration  = reading_dict.get("acceleration", 0.0),
                risk_score    = reading_dict.get("risk_score", 0.0),
                anomaly_score = reading_dict.get("anomaly_score", 0.0),
                status        = reading_dict.get("status", "NORMAL"),
                sensor_mode   = reading_dict.get("mode", "MOCK"),
            )
            db.session.add(row)
            db.session.commit()
    except Exception as exc:
        log.error("Database write error: %s", exc)


def get_history(limit: int = 100):
    """
    Return the most recent `limit` readings, newest first.
    Called inside an active Flask app context.
    """
    try:
        rows = (
            SensorReading.query
            .order_by(SensorReading.id.desc())
            .limit(limit)
            .all()
        )
        return [r.to_dict() for r in rows]
    except Exception as exc:
        log.error("Database read error: %s", exc)
        return []


def get_statistics():
    """
    Return aggregate statistics over all stored readings.
    Called inside an active Flask app context.
    """
    try:
        from sqlalchemy import func
        result = db.session.query(
            func.count(SensorReading.id).label("total_readings"),
            func.min(SensorReading.distance).label("min_distance"),
            func.max(SensorReading.distance).label("max_distance"),
            func.avg(SensorReading.distance).label("avg_distance"),
            func.max(SensorReading.risk_score).label("max_risk"),
            func.avg(SensorReading.risk_score).label("avg_risk"),
        ).one()

        # Count readings per status
        status_counts = {}
        for status in ["NORMAL", "CAUTION", "WARNING", "CRITICAL"]:
            count = SensorReading.query.filter_by(status=status).count()
            status_counts[status.lower()] = count

        return {
            "total_readings": result.total_readings or 0,
            "min_distance":   round(result.min_distance or 0, 2),
            "max_distance":   round(result.max_distance or 0, 2),
            "avg_distance":   round(result.avg_distance or 0, 2),
            "max_risk_score": round(result.max_risk or 0, 1),
            "avg_risk_score": round(result.avg_risk or 0, 1),
            "status_counts":  status_counts,
        }
    except Exception as exc:
        log.error("Statistics query error: %s", exc)
        return {}
