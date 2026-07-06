# Agent 4: Value Sanity Agent
# Checks sensor readings against physical valid ranges
# Rules-based only - runs only if trust score passed agent 3

VALID_RANGES = {
    "soil_moisture": (0, 100),
    "temperature":   (-20, 60),
    "humidity":      (0, 100),
    "rainfall":      (0, 500),
    "ph":            (0, 14),
    "nitrogen":      (0, 500),
    "phosphorus":    (0, 500),
    "potassium":     (0, 500),
}

class ValueSanityAgent:

    def run(self, raw_readings: dict) -> dict:
        fields_checked = 0
        fields_passed = 0
        failed_fields = []

        for field, (min_val, max_val) in VALID_RANGES.items():
            if field in raw_readings:
                fields_checked += 1
                value = raw_readings[field]

                if isinstance(value, (int, float)) and min_val <= value <= max_val:
                    fields_passed += 1
                else:
                    failed_fields.append(field)

        if fields_checked == 0:
            return {
                "passed": False,
                "sanity_score": 0.0,
                "reason": "No expected fields found"
            }

        sanity_score = round(fields_passed / fields_checked, 3)

        return {
            "passed": True,  # never hard fails, just scores
            "sanity_score": sanity_score,
            "failed_fields": failed_fields,
            "reason": f"{fields_passed}/{fields_checked} fields passed sanity check"
        }