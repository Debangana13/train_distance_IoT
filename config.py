"""
config.py — Central configuration for the AI Train Distance Alert System.

All settings are loaded from environment variables (or a .env file).
This means you can switch between MOCK and HARDWARE modes without
touching any Python code — just change the .env file.
"""

import os
from dotenv import load_dotenv

# Load .env file if it exists (silently ignored if not found)
load_dotenv()

# --------------------------------------------------------------------------
# Application Mode
# --------------------------------------------------------------------------
# "MOCK"     → Use the built-in scenario simulator (no Arduino needed)
# "HARDWARE" → Read real sensor data from Arduino via USB serial
APP_MODE = os.getenv("APP_MODE", "MOCK").upper()
IS_MOCK = APP_MODE == "MOCK"

# --------------------------------------------------------------------------
# Serial / Arduino Settings (only used in HARDWARE mode)
# --------------------------------------------------------------------------
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM5")
BAUD_RATE = int(os.getenv("BAUD_RATE", "9600"))

# --------------------------------------------------------------------------
# Alert Thresholds (centimetres)
# --------------------------------------------------------------------------
# Risk score boundaries (0–100 scale):
#   0–39   → NORMAL
#  40–59   → CAUTION
#  60–79   → WARNING
#  80–100  → CRITICAL
#
# Independent distance-based safety override:
#   distance <= CRITICAL_DISTANCE → always CRITICAL
CRITICAL_DISTANCE = float(os.getenv("CRITICAL_DISTANCE", "30"))
WARNING_DISTANCE = float(os.getenv("WARNING_DISTANCE", "50"))

# --------------------------------------------------------------------------
# Data / Sampling
# --------------------------------------------------------------------------
# Minimum seconds between database writes to avoid duplicate rows
SAMPLE_INTERVAL = float(os.getenv("SAMPLE_INTERVAL", "1.0"))

# Maximum readings kept in the in-memory ring buffer
BUFFER_SIZE = 120

# Number of recent readings used to compute the moving average
MA_WINDOW = 5

# Maximum chart history points served to the frontend
MAX_HISTORY = 100

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "train_alert.db")
SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"

# --------------------------------------------------------------------------
# Flask
# --------------------------------------------------------------------------
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"
