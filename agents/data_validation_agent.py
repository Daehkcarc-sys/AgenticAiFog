# Agent 1: Data Validation
# Checks format, required fields, sensor identity
# Rules-based only - no LLM needed, must be fast

SENSOR_REGISTRY = [
    "SENSOR_001",
    "SENSOR_002",
    "SENSOR_003"
]

REQUIRED_FIELDS = [
    "soil_moisture", "temperature", "humidity",
    "rainfall", "ph", "nitrogen", "phosphorus", "potassium"
]

class DataValidationAgent:

    def run(self, sensor_data: dict) -> dict:
        sensor_id = sensor_data.get("sensor_id", "")
        raw_readings = sensor_data.get("raw_readings", {})
        tinyml_output = sensor_data.get("tinyml_output", {})

        # check 1: sensor identity
        if sensor_id.upper() not in SENSOR_REGISTRY:
            return {
                "passed": False,
                "reason": f"Unknown sensor identity: {sensor_id}"
            }

        # check 2: required fields present
        missing = [f for f in REQUIRED_FIELDS if f not in raw_readings]
        if missing:
            return {
                "passed": False,
                "reason": f"Missing required fields: {missing}"
            }

        # check 3: tinyml output present
        if not tinyml_output:
            return {
                "passed": False,
                "reason": "Missing TinyML output"
            }

        # check 4: criticality flag present
        if "recommended_action" not in tinyml_output:
            return {
                "passed": False,
                "reason": "TinyML output missing recommended_action"
            }

        return {"passed": True, "reason": "Data validation passed"}