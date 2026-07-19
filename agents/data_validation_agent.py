from __future__ import annotations

from config import ALLOWED_ACTIONS, OPTIONAL_FIELDS, REQUIRED_FIELDS, VALID_RANGES
from models import ValidationResult
from sensor_registry import SensorRegistry


class DataValidationAgent:
    """Trust Layer — validates sensor identity, schema, and TinyML output.

    Returns a ``ValidationResult`` that supports both attribute access
    (``.passed``) and dict-style access (``["passed"]``).

    Uses ``ALLOWED_ACTIONS`` (the full action vocabulary including cloud
    and validation) for TinyML validation, not the physical ``ACTION_WHITELIST``
    — the TinyML should be allowed to recommend escalation.
    """

    def run(self, sensor_data: dict) -> ValidationResult:
        sensor_id = sensor_data.get("sensor_id", "")
        raw_readings = sensor_data.get("raw_readings", {})
        tinyml_output = sensor_data.get("tinyml_output", {})

        if not SensorRegistry.is_registered(sensor_id):
            return ValidationResult(
                passed=False,
                reason=f"Unknown sensor identity: {sensor_id}",
            )

        missing = [field for field in REQUIRED_FIELDS if field not in raw_readings]
        if missing:
            return ValidationResult(
                passed=False,
                reason=f"Missing required fields: {missing}",
            )

        unknown_fields = [
            field
            for field in raw_readings
            if field not in REQUIRED_FIELDS and field not in OPTIONAL_FIELDS
        ]
        if unknown_fields:
            return ValidationResult(
                passed=False,
                reason=f"Unknown raw reading fields: {unknown_fields}",
            )

        non_numeric = [
            field
            for field, value in raw_readings.items()
            if field in VALID_RANGES and not isinstance(value, (int, float))
        ]
        if non_numeric:
            return ValidationResult(
                passed=False,
                reason=f"Non-numeric sensor fields: {non_numeric}",
            )

        if not isinstance(tinyml_output, dict) or not tinyml_output:
            return ValidationResult(
                passed=False,
                reason="Missing TinyML output",
            )

        action = tinyml_output.get("recommended_action")
        if not action or action not in ALLOWED_ACTIONS:
            return ValidationResult(
                passed=False,
                reason=f"Invalid TinyML recommended_action: {action}",
            )

        confidence = tinyml_output.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
            return ValidationResult(
                passed=False,
                reason=f"Invalid TinyML confidence: {confidence}",
            )

        return ValidationResult(passed=True, reason="Data validation passed")
