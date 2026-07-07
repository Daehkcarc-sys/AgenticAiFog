from __future__ import annotations

from config import ACTION_WHITELIST, REQUIRED_FIELDS
from sensor_registry import SensorRegistry


class DataValidationAgent:

    def run(self, sensor_data: dict) -> dict:
        sensor_id = sensor_data.get("sensor_id", "")
        raw_readings = sensor_data.get("raw_readings", {})
        tinyml_output = sensor_data.get("tinyml_output", {})

        if not SensorRegistry.is_registered(sensor_id):
            return {
                "passed": False,
                "reason": f"Unknown sensor identity: {sensor_id}"
            }

        missing = [field for field in REQUIRED_FIELDS if field not in raw_readings]
        if missing:
            return {
                "passed": False,
                "reason": f"Missing required fields: {missing}"
            }

        if not isinstance(tinyml_output, dict) or not tinyml_output:
            return {
                "passed": False,
                "reason": "Missing TinyML output"
            }

        action = tinyml_output.get("recommended_action")
        if not action or action not in ACTION_WHITELIST:
            return {
                "passed": False,
                "reason": f"Invalid TinyML recommended_action: {action}"
            }

        confidence = tinyml_output.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
            return {
                "passed": False,
                "reason": f"Invalid TinyML confidence: {confidence}"
            }

        return {"passed": True, "reason": "Data validation passed"}
