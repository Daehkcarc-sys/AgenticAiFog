from __future__ import annotations

import warnings
from datetime import datetime, timezone

from config import FRESHNESS_LIMIT_SECONDS, SENSOR_REGISTRY, TRUST_LEVEL_THRESHOLDS, VALID_RANGES

warnings.warn(
    "trust_scorer.TrustScorer is deprecated. "
    "Use agents.trust_score_agent.TrustScoreAgent via the FogPipeline instead.",
    DeprecationWarning,
    stacklevel=2,
)

WEIGHTS = {
    "identity": 0.35,
    "freshness": 0.15,
    "sanity": 0.25,
    "consistency": 0.25,
}


class TrustScorer:

    def __init__(self, freshness_limit_seconds: int = FRESHNESS_LIMIT_SECONDS):
        self.freshness_limit = freshness_limit_seconds

    def check_identity(self, sensor_id: str) -> float:
        if sensor_id.upper() in {sensor.upper() for sensor in SENSOR_REGISTRY}:
            return 1.0
        return 0.0

    def check_freshness(self, timestamp: str) -> float:
        try:
            reading_time = datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - reading_time).total_seconds()

            if age_seconds < 60:
                return 1.0
            if age_seconds < 180:
                return 0.8
            if age_seconds < self.freshness_limit:
                return 0.6
            if age_seconds < 600:
                return 0.3
            return 0.0

        except ValueError:
            return 0.0

    def check_value_sanity(self, readings: dict) -> float:
        fields_checked = 0
        fields_passed = 0

        for field, (min_val, max_val) in VALID_RANGES.items():
            if field in readings:
                fields_checked += 1
                value = readings[field]
                if isinstance(value, (int, float)) and min_val <= value <= max_val:
                    fields_passed += 1

        if fields_checked == 0:
            return 0.0

        return fields_passed / fields_checked

    def check_consistency(self, readings: dict, tinyml_output: dict) -> float:
        action = tinyml_output.get("recommended_action", "").lower()
        confidence = tinyml_output.get("confidence", 0.5)
        soil_moisture = readings.get("soil_moisture")

        if soil_moisture is None:
            return 0.5

        if action == "irrigate":
            if soil_moisture > 80:
                return 0.4 * (1 - confidence * 0.5)
            if soil_moisture > 50:
                return 0.65
            return 1.0

        if action == "no_action":
            if soil_moisture < 20:
                return 0.4 * (1 - confidence * 0.5)
            if soil_moisture < 40:
                return 0.65
            return 1.0

        return 0.3

    def score(self, sensor_data: dict) -> float:
        identity = self.check_identity(sensor_data.get("sensor_id", ""))
        if identity == 0.0:
            return 0.0

        freshness = self.check_freshness(sensor_data.get("timestamp", ""))
        sanity = self.check_value_sanity(sensor_data.get("raw_readings", {}))
        consistency = self.check_consistency(
            sensor_data.get("raw_readings", {}),
            sensor_data.get("tinyml_output", {}),
        )

        final_score = (
            identity * WEIGHTS["identity"]
            + freshness * WEIGHTS["freshness"]
            + sanity * WEIGHTS["sanity"]
            + consistency * WEIGHTS["consistency"]
        )

        return round(final_score, 3)

    def is_trusted(self, score: float) -> bool:
        return score >= 0.6

    def get_trust_level(self, score: float) -> str:
        if score >= TRUST_LEVEL_THRESHOLDS["HIGH"]:
            return "HIGH"
        if score >= TRUST_LEVEL_THRESHOLDS["MEDIUM"]:
            return "MEDIUM"
        return "LOW"
