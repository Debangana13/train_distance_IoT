"""
services/ai_service.py — AI / Machine Learning Risk Analysis Engine.

================================================================================
HOW THE AI WORKS (for your viva explanation)
================================================================================

This module implements an AI-assisted risk analysis layer for the IoT prototype.
It is NOT a certified railway safety system — it is an educational demonstration
of how machine learning can enhance IoT sensor data.

IMPLEMENTATION NOTE ON scikit-learn:
-------------------------------------
scikit-learn requires pre-built binary wheels that are not yet available for
Python 3.14. This module implements the Isolation Forest algorithm directly
in NumPy so the app works on any Python version. If scikit-learn is installed
(e.g. via a compatible Python version), it is used automatically; otherwise
the built-in NumPy implementation is used. The results are equivalent.

ALGORITHM EXPLANATION:
-----------------------

STEP 1 — Feature Engineering
------------------------------
Instead of feeding raw distance alone, we compute several derived features:

  • distance       : The current measured distance (cm)
  • prev_distance  : Distance from the previous reading
  • velocity       : Rate of distance change (cm/s). Negative = approaching.
  • acceleration   : Rate of velocity change (cm/s²)
  • moving_avg     : Rolling mean of the last 5 distances (smooths noise)
  • dist_from_avg  : How far current reading deviates from moving average

STEP 2 — Isolation Forest (Anomaly Detection)
----------------------------------------------
Isolation Forest works by randomly splitting the feature space:
  - Normal data points are hard to isolate (require many splits → long path)
  - Anomalous data points are easy to isolate (few splits → short path)

Each "tree" randomly selects a feature and a random split value. The average
path length across all trees gives the anomaly score.

This NumPy implementation:
  - Trains on 800 synthetic "normal" readings
  - Uses 100 trees with max depth 10
  - Computes path length for each new reading

STEP 3 — Risk Sub-scores
--------------------------
Four components (each 0.0–1.0):
  proximity_risk   : How close is the object?
  velocity_risk    : How fast is it approaching?
  acceleration_risk: Is it suddenly accelerating toward us?
  anomaly_risk     : Does the ML model flag this as unusual?

STEP 4 — Weighted Combination
------------------------------
risk_score = 100 × (0.40×proximity + 0.30×velocity + 0.15×accel + 0.15×anomaly)

STEP 5 — Status Classification
--------------------------------
  risk_score < 40               → NORMAL
  40 ≤ risk_score < 60          → CAUTION
  60 ≤ risk_score < 80          → WARNING
  risk_score ≥ 80               → CRITICAL
  distance ≤ CRITICAL_DISTANCE  → CRITICAL (safety override)

STEP 6 — Time-to-Critical Prediction
--------------------------------------
If approaching: time = (distance - CRITICAL_DISTANCE) / |velocity|
================================================================================
"""

import logging
import numpy as np

import config

log = logging.getLogger(__name__)

# Try to use scikit-learn if available (pre-built wheels exist for Python < 3.14)
try:
    from sklearn.ensemble import IsolationForest as SklearnIF
    _SKLEARN_AVAILABLE = True
    log.info("scikit-learn available — using sklearn IsolationForest")
except ImportError:
    _SKLEARN_AVAILABLE = False
    log.info("scikit-learn not available — using built-in NumPy Isolation Forest implementation")


# ============================================================
# Built-in NumPy Isolation Forest Implementation
# (Used when scikit-learn is not installed)
# ============================================================

class _IsolationTree:
    """
    A single isolation tree: recursively partitions the feature space
    by selecting random features and random split values.

    Anomalous points are isolated quickly (short paths).
    Normal points require more splits (longer paths).
    """

    def __init__(self, max_depth: int):
        self.max_depth = max_depth
        self.left      = None
        self.right     = None
        self.split_feat = None
        self.split_val  = None
        self.depth      = 0
        self.size       = 0    # number of training samples at this node

    def fit(self, X: np.ndarray, depth: int = 0):
        """Build the tree recursively."""
        self.size  = len(X)
        self.depth = depth

        # Stop splitting if: only 1 sample, or max depth reached
        if len(X) <= 1 or depth >= self.max_depth:
            return self

        n_features = X.shape[1]
        self.split_feat = np.random.randint(0, n_features)

        col      = X[:, self.split_feat]
        col_min  = col.min()
        col_max  = col.max()

        if col_min == col_max:
            return self   # all values the same — can't split

        self.split_val = np.random.uniform(col_min, col_max)

        mask      = col < self.split_val
        left_X    = X[mask]
        right_X   = X[~mask]

        self.left  = _IsolationTree(self.max_depth).fit(left_X,  depth + 1)
        self.right = _IsolationTree(self.max_depth).fit(right_X, depth + 1)

        return self

    def path_length(self, x: np.ndarray, current_depth: int = 0) -> float:
        """Return the path length (depth) needed to isolate sample x."""
        # Leaf node: adjust by expected path length for remaining samples
        if self.left is None or self.right is None or self.split_feat is None:
            return current_depth + self._expected_path_length(self.size)

        if x[self.split_feat] < self.split_val:
            return self.left.path_length(x, current_depth + 1)
        else:
            return self.right.path_length(x, current_depth + 1)

    @staticmethod
    def _expected_path_length(n: int) -> float:
        """Average path length in a binary search tree with n samples."""
        if n <= 1:
            return 0.0
        # Harmonic number approximation: 2 * (ln(n-1) + 0.5772) - 2*(n-1)/n
        return 2.0 * (np.log(n - 1) + 0.5772156649) - (2.0 * (n - 1) / n)


class _NumpyIsolationForest:
    """
    Pure NumPy Isolation Forest with the same interface as sklearn's.

    Implements the original algorithm from:
    Liu, Fei Tony, Kai Ming Ting, and Zhi-Hua Zhou.
    "Isolation forest." ICDM 2008.
    """

    def __init__(self, n_estimators: int = 100, max_samples: int = 256,
                 contamination: float = 0.05, random_state: int = 42):
        self.n_estimators  = n_estimators
        self.max_samples   = max_samples
        self.contamination = contamination
        np.random.seed(random_state)
        self.trees_          = []
        self._c_norm         = 1.0    # normalisation constant
        self._threshold      = 0.0   # anomaly score threshold

    def fit(self, X: np.ndarray):
        """Train the forest on training data X."""
        n      = len(X)
        sample = min(self.max_samples, n)
        depth  = int(np.ceil(np.log2(sample))) + 1
        self._c_norm = _IsolationTree._expected_path_length(sample)

        self.trees_ = []
        for _ in range(self.n_estimators):
            idx  = np.random.choice(n, sample, replace=False)
            tree = _IsolationTree(depth).fit(X[idx])
            self.trees_.append(tree)

        # Compute threshold based on training data scores
        scores = self._raw_scores(X)
        self._threshold = np.percentile(scores, 100 * (1 - self.contamination))
        return self

    def _raw_scores(self, X: np.ndarray) -> np.ndarray:
        """Compute raw anomaly scores for each sample in X."""
        scores = np.zeros(len(X))
        for i, x in enumerate(X):
            avg_path = np.mean([t.path_length(x) for t in self.trees_])
            # Anomaly score: 1 = very anomalous, 0 = very normal
            if self._c_norm > 0:
                scores[i] = 2 ** (-avg_path / self._c_norm)
            else:
                scores[i] = 0.5
        return scores

    def decision_function(self, X: np.ndarray) -> np.ndarray:
        """
        Returns anomaly scores in the same sign convention as sklearn:
          positive = normal (inlier)
          negative = anomalous (outlier)
        """
        raw = self._raw_scores(X)
        # Shift so that values above threshold (normal) are positive
        return self._threshold - raw


# ============================================================
# Main AI Risk Engine
# ============================================================

class AIRiskEngine:
    """
    AI risk analysis engine for IoT distance monitoring.

    Uses Isolation Forest for anomaly detection combined with
    physics-based risk scoring for real-time danger assessment.
    """

    def __init__(self):
        log.info("Initialising AI Risk Engine...")
        self._train_model()
        log.info("AI Risk Engine ready (backend: %s).",
                 "sklearn" if _SKLEARN_AVAILABLE else "numpy-native")

    def _train_model(self):
        """
        Train the Isolation Forest on synthetic 'normal' sensor data.

        Normal behaviour:
          - Object at a safe distance (60–120 cm)
          - Low-speed movements
          - Low acceleration
          - Readings close to the moving average
        """
        rng = np.random.default_rng(42)
        n   = 800

        distance      = rng.normal(85, 12, n).clip(40, 200)
        prev_distance = distance + rng.normal(0, 1.5, n)
        velocity      = rng.normal(0, 2.0, n)
        acceleration  = rng.normal(0, 0.5, n)
        moving_avg    = distance + rng.normal(0, 1.0, n)
        dist_from_avg = np.abs(distance - moving_avg)

        X = np.column_stack([distance, prev_distance, velocity,
                              acceleration, moving_avg, dist_from_avg])

        if _SKLEARN_AVAILABLE:
            self.model = SklearnIF(
                n_estimators=200,
                contamination=0.04,
                random_state=42,
                n_jobs=-1
            )
        else:
            self.model = _NumpyIsolationForest(
                n_estimators=100,
                max_samples=256,
                contamination=0.04,
                random_state=42,
            )

        self.model.fit(X)

    def predict(self, distance: float, prev_distance: float,
                velocity: float, acceleration: float,
                moving_avg: float) -> dict:
        """
        Compute the full AI risk assessment for one sensor reading.

        Parameters
        ----------
        distance      : Current distance reading (cm)
        prev_distance : Previous reading (cm)
        velocity      : Rate of change (cm/s). Negative = approaching.
        acceleration  : Rate of velocity change (cm/s²)
        moving_avg    : Rolling mean of recent readings (cm)

        Returns
        -------
        dict with risk_score, anomaly_score, status, trend, sub-scores,
        and time_to_critical
        """
        dist_from_avg = abs(distance - moving_avg)
        x = np.array([[distance, prev_distance, velocity,
                        acceleration, moving_avg, dist_from_avg]])

        # --- Isolation Forest anomaly score ---
        # decision_function: positive = normal, negative = anomalous
        raw_anomaly   = float(self.model.decision_function(x)[0])
        anomaly_score = max(0.0, min(1.0, (0.10 - raw_anomaly) / 0.30))

        # --- Sub-scores (each 0.0 to 1.0) ---
        proximity_risk = max(0.0, min(1.0,
            (config.WARNING_DISTANCE - distance) / config.WARNING_DISTANCE + 0.20
        ))

        approach_speed = max(0.0, -velocity)
        velocity_risk  = max(0.0, min(1.0, approach_speed / 15.0))

        neg_accel  = max(0.0, -acceleration)
        accel_risk = max(0.0, min(1.0, neg_accel / 8.0))

        # --- Weighted risk score 0–100 ---
        risk_score = 100.0 * (
            0.40 * proximity_risk +
            0.30 * velocity_risk  +
            0.15 * accel_risk     +
            0.15 * anomaly_score
        )
        risk_score = round(max(0.0, min(100.0, risk_score)), 1)

        # --- Status (with distance safety override) ---
        if distance <= config.CRITICAL_DISTANCE:
            status = "CRITICAL"
        elif risk_score >= 80:
            status = "CRITICAL"
        elif risk_score >= 60:
            status = "WARNING"
        elif risk_score >= 40:
            status = "CAUTION"
        else:
            status = "NORMAL"

        # --- Trend ---
        if velocity < -1.5:
            trend = "APPROACHING"
        elif velocity > 1.5:
            trend = "RECEDING"
        else:
            trend = "STABLE"

        # --- Time-to-critical ---
        time_to_critical = self._estimate_ttc(distance, velocity)

        return {
            "risk_score":      risk_score,
            "anomaly_score":   round(anomaly_score, 3),
            "status":          status,
            "trend":           trend,
            "proximity_risk":  round(proximity_risk * 100, 1),
            "velocity_risk":   round(velocity_risk * 100, 1),
            "accel_risk":      round(accel_risk * 100, 1),
            "time_to_critical": time_to_critical,
        }

    def _estimate_ttc(self, distance: float, velocity: float):
        """
        Estimate seconds until object reaches CRITICAL_DISTANCE.
        Returns None if not approaching, 0.0 if already at critical.
        """
        approach_speed = -velocity
        if approach_speed < 0.5:
            return None
        remaining = distance - config.CRITICAL_DISTANCE
        if remaining <= 0:
            return 0.0
        return round(remaining / approach_speed, 1)
