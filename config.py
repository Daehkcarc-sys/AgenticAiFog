from __future__ import annotations

from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
DATA_PATH = DATA_DIR / "archive" / "Crop_recommendationV2.csv"
DATA_ARCHIVE_PATH = DATA_DIR / "archive.zip"
LOG_PATH = LOG_DIR / "decisions.json"
METRICS_PATH = LOG_DIR / "metrics.json"

# Trusted sensor identities for the fog domain
SENSOR_REGISTRY: List[str] = [
    "SENSOR_001",
    "SENSOR_002",
    "SENSOR_003",
]

# Required raw fields for the current agricultural digital twin prototype
REQUIRED_FIELDS: List[str] = [
    "soil_moisture",
    "temperature",
    "humidity",
    "rainfall",
    "ph",
    "nitrogen",
    "phosphorus",
    "potassium",
]

# Valid physical ranges for sensor readings in the environment
VALID_RANGES: Dict[str, tuple[float, float]] = {
    "soil_moisture": (0, 100),
    "temperature": (-20, 60),
    "humidity": (0, 100),
    "rainfall": (0, 500),
    "ph": (0, 14),
    "nitrogen": (0, 500),
    "phosphorus": (0, 500),
    "potassium": (0, 500),
}

# Conservative operating envelope used only to identify clearly normal
# readings. These limits are intentionally narrower than VALID_RANGES,
# which describe physical plausibility rather than healthy crop conditions.
NORMAL_OPERATING_RANGES: Dict[str, tuple[float, float]] = {
    "soil_moisture": (40, 70),
    "temperature": (15, 35),
    "humidity": (30, 85),
    "ph": (5.5, 8.0),
}

# Supported actions in the fog action loop
ALLOWED_ACTIONS: List[str] = [
    "irrigate",
    "stop_irrigation",
    "adjust_flow",
    "trigger_alert",
    "no_action",
    "cloud",
    "validation",
]

ACTION_WHITELIST: List[str] = [
    "irrigate",
    "stop_irrigation",
    "adjust_flow",
    "trigger_alert",
    "no_action",
]

# Research-oriented feature taxonomy for the digital twin
FEATURE_GROUPS: Dict[str, List[str]] = {
    "climate": ["temperature", "humidity", "rainfall", "wind"],
    "soil": ["soil_moisture", "ph", "salinity", "nitrogen", "phosphorus", "potassium"],
    "water_system": ["tank_level", "irrigation_flow", "valve_state"],
    "crop_state": ["leaf_wetness", "color_index", "growth_rate"],
    "system_state": ["packet_loss", "missing_data", "sensor_trust_score"],
}

TRUST_LEVEL_THRESHOLDS = {
    "HIGH": 0.8,
    "MEDIUM": 0.5,
    "LOW": 0.0,
}

FRESHNESS_LIMIT_SECONDS = 300
FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 5
EARLY_EXIT_THRESHOLD = 0.5
LOCAL_ACTION_MIN_SANITY_SCORE = 0.9
