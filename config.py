from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
DATA_PATH = DATA_DIR / "archive" / "Crop_recommendationV2.csv"
DATA_ARCHIVE_PATH = DATA_DIR / "archive.zip"
LOG_PATH = LOG_DIR / "decisions.json"
METRICS_PATH = LOG_DIR / "metrics.json"
QUEUE_DIR = LOG_DIR / "queues"
STATE_DIR = ROOT_DIR / "state"
CACHE_PATH = STATE_DIR / "decision_cache.json"
RULE_STORE_PATH = STATE_DIR / "local_rules.json"
MODEL_STORE_PATH = STATE_DIR / "model_store.json"
AUDIT_CHAIN_PATH = LOG_DIR / "security_audit_chain.jsonl"

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

# Optional IoT fields supported by context, validation, and anomaly checks.
OPTIONAL_FIELDS: List[str] = [
    "pressure",
    "wind",
    "salinity",
    "tank_level",
    "irrigation_flow",
    "valve_state",
    "leaf_wetness",
    "color_index",
    "growth_rate",
    "packet_loss",
    "missing_data",
    "sensor_trust_score",
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
    "pressure": (300, 1200),
    "wind": (0, 80),
    "salinity": (0, 20),
    "tank_level": (0, 100),
    "irrigation_flow": (0, 1000),
    "valve_state": (0, 1),
    "leaf_wetness": (0, 100),
    "color_index": (0, 1),
    "growth_rate": (-10, 20),
    "packet_loss": (0, 100),
    "missing_data": (0, 100),
    "sensor_trust_score": (0, 1),
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

# Integration endpoints are optional. If unset, the project uses durable local
# queues/files so it remains runnable on a development machine.
ACTUATOR_MODE = os.getenv("ACTUATOR_MODE", "local_queue")
ACTUATOR_HTTP_ENDPOINT = os.getenv("ACTUATOR_HTTP_ENDPOINT")
ACTUATOR_MQTT_HOST = os.getenv("ACTUATOR_MQTT_HOST")
ACTUATOR_MQTT_PORT = int(os.getenv("ACTUATOR_MQTT_PORT", "1883"))
ACTUATOR_MQTT_TOPIC = os.getenv("ACTUATOR_MQTT_TOPIC", "fog/actuators")
ACTUATOR_COMMAND_TEMPLATE = os.getenv("ACTUATOR_COMMAND_TEMPLATE")

CLOUD_SYNC_MODE = os.getenv("CLOUD_SYNC_MODE", "local_queue")
CLOUD_HTTP_ENDPOINT = os.getenv("CLOUD_HTTP_ENDPOINT")
CLOUD_KAFKA_BOOTSTRAP = os.getenv("CLOUD_KAFKA_BOOTSTRAP")
CLOUD_KAFKA_TOPIC = os.getenv("CLOUD_KAFKA_TOPIC", "sensor-data")
CLOUD_HEALTH_URL = os.getenv("CLOUD_HEALTH_URL")

SECURITY_HMAC_SECRET = os.getenv("SECURITY_HMAC_SECRET", "dev-fog-secret")

CRITICALITY_MODE = os.getenv("CRITICALITY_MODE", "local_first")
CRITICALITY_ENABLE_REMOTE_FALLBACK = (
    os.getenv("CRITICALITY_ENABLE_REMOTE_FALLBACK", "false").lower()
    in {"1", "true", "yes", "on"}
)
CRITICALITY_AMBIGUITY_MARGIN = int(os.getenv("CRITICALITY_AMBIGUITY_MARGIN", "1"))
