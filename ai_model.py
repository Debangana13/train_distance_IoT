import numpy as np
from sklearn.ensemble import IsolationForest

class AIRiskEngine:
    """
    AI layer:
    - Learns what normal distance/approach behaviour looks like.
    - Isolation Forest gives an anomaly score.
    - A small risk model combines distance, approach velocity and anomaly.

    The hardware safety rule remains independent: Arduino still controls
    the LED/buzzer at <= 30 cm.
    """

    def __init__(self):
        # Demonstration baseline: stable measurements from a safe distance.
        # Replace this with collected real-world normal readings for a stronger model.
        rng = np.random.default_rng(42)
        normal_distance = rng.normal(80, 8, 500)
        normal_velocity = np.abs(rng.normal(0.5, 0.35, 500))
        X = np.column_stack([normal_distance, normal_velocity])

        self.model = IsolationForest(
            n_estimators=150,
            contamination=0.05,
            random_state=42
        )
        self.model.fit(X)

    def predict(self, distance, velocity):
        x = np.array([[distance, velocity]])
        raw = float(self.model.decision_function(x)[0])

        # Convert anomaly information to 0-100. This is a presentation score,
        # not a certified safety probability.
        anomaly = max(0.0, min(1.0, (0.15 - raw) / 0.30))

        proximity = max(0.0, min(1.0, (50.0 - distance) / 50.0))
        approach = max(0.0, min(1.0, velocity / 10.0))

        score = round(100 * (0.50 * proximity + 0.25 * approach + 0.25 * anomaly), 1)

        if score >= 75:
            status = "CRITICAL"
        elif score >= 45:
            status = "WARNING"
        else:
            status = "NORMAL"

        return {"score": score, "status": status}
