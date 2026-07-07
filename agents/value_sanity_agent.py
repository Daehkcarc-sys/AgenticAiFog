from __future__ import annotations

from config import VALID_RANGES


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
            "passed": True,
            "sanity_score": sanity_score,
            "failed_fields": failed_fields,
            "reason": f"{fields_passed}/{fields_checked} fields passed sanity check"
        }
