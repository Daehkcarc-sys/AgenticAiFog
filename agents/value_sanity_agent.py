"""Trust Layer — physical + semantic sanity validation for sensor readings.

Checks each field against valid physical ranges and cross-validates
readings against the TinyML recommendation for semantic consistency.
"""

from __future__ import annotations

from config import VALID_RANGES
from models import SanityResult


class ValueSanityAgent:
    """Trust Layer — physical range + semantic consistency validation.

    Performs three levels of assessment:
    1. Physical: each field within its valid range?
    2. Statistical: extreme values that suggest sensor malfunction?
    3. Semantic: do readings contradict the TinyML recommendation?

    Returns a ``SanityResult`` with ``passed=False`` only when there is
    high confidence that the data is invalid (e.g., physically impossible
    values).  Minor anomalies are reported as warnings via ``anomalies``
    so downstream agents can factor them into decisions.
    """

    # Fields where any value outside the valid range is physically
    # impossible and should trigger a hard reject.
    _HARD_REJECT_FIELDS: frozenset[str] = frozenset(
        {"temperature", "humidity", "ph", "soil_moisture"}
    )

    # Multiplier thresholds for "extreme" statistical anomaly detection.
    # A value is considered extreme if it exceeds (max - min) * threshold
    # beyond the valid range.
    _EXTREME_MULTIPLIER: float = 2.0

    def run(
        self, raw_readings: dict, tinyml_output: dict | None = None
    ) -> SanityResult:
        fields_checked = 0
        fields_passed = 0
        failed_fields: list[str] = []
        anomalies: list[str] = []
        hard_failures: list[str] = []

        for field, (min_val, max_val) in VALID_RANGES.items():
            if field not in raw_readings:
                continue
            fields_checked += 1
            value = raw_readings[field]

            if not isinstance(value, (int, float)):
                failed_fields.append(field)
                anomalies.append(f"{field}: non-numeric value {type(value).__name__}")
                if field in self._HARD_REJECT_FIELDS:
                    hard_failures.append(field)
                continue

            in_range = min_val <= value <= max_val

            if in_range:
                fields_passed += 1
                # Check for borderline values (within 5% of range edge)
                margin = (max_val - min_val) * 0.05
                if value <= min_val + margin or value >= max_val - margin:
                    anomalies.append(
                        f"{field}: borderline ({value}, range [{min_val}, {max_val}])"
                    )
            else:
                failed_fields.append(field)
                # Determine severity
                extreme_range = (max_val - min_val) * self._EXTREME_MULTIPLIER
                if value < min_val - extreme_range or value > max_val + extreme_range:
                    anomalies.append(
                        f"{field}: EXTREME outlier ({value}, range [{min_val}, {max_val}])"
                    )
                    if field in self._HARD_REJECT_FIELDS:
                        hard_failures.append(field)
                else:
                    anomalies.append(
                        f"{field}: out of range ({value}, range [{min_val}, {max_val}])"
                    )

        # ── Semantic consistency with TinyML ──────────────
        if tinyml_output:
            sem_anomalies = self._check_semantic_consistency(
                raw_readings, tinyml_output
            )
            anomalies.extend(sem_anomalies)

        # ── Decision ──────────────────────────────────────
        if fields_checked == 0:
            return SanityResult(
                passed=False,
                sanity_score=0.0,
                failed_fields=[],
                reason="No expected fields found",
            )

        sanity_score = round(fields_passed / fields_checked, 3)

        # Hard-reject only when physically impossible values exist
        if hard_failures:
            return SanityResult(
                passed=False,
                sanity_score=sanity_score,
                failed_fields=hard_failures,
                reason=(
                    f"Physically impossible values in: {hard_failures}. "
                    f"Anomalies: {'; '.join(anomalies)}"
                ),
            )

        # Pass with warnings
        if anomalies:
            return SanityResult(
                passed=True,
                sanity_score=sanity_score,
                failed_fields=failed_fields,
                reason=(
                    f"{fields_passed}/{fields_checked} fields OK. "
                    f"Warnings: {'; '.join(anomalies)}"
                ),
            )

        return SanityResult(
            passed=True,
            sanity_score=sanity_score,
            failed_fields=[],
            reason=f"{fields_passed}/{fields_checked} fields passed sanity check",
        )

    @staticmethod
    def _check_semantic_consistency(
        readings: dict, tinyml_output: dict
    ) -> list[str]:
        """Cross-validate readings against the TinyML recommendation."""
        anomalies: list[str] = []
        action = tinyml_output.get("recommended_action", "").lower()
        moisture = readings.get("soil_moisture")
        temperature = readings.get("temperature")

        if moisture is not None:
            if action == "irrigate" and moisture > 80:
                anomalies.append(
                    f"TinyML recommends 'irrigate' but soil moisture is "
                    f"{moisture}% — possible sensor error or model drift"
                )
            elif action == "stop_irrigation" and moisture < 30:
                anomalies.append(
                    f"TinyML recommends 'stop_irrigation' but soil moisture is "
                    f"{moisture}% — crops may need water"
                )
            elif action == "no_action" and moisture < 15:
                anomalies.append(
                    f"TinyML recommends 'no_action' but soil moisture is "
                    f"{moisture}% — drought risk"
                )

        if temperature is not None:
            if isinstance(temperature, (int, float)):
                if temperature > 55:
                    anomalies.append(
                        f"Temperature {temperature}°C — extreme heat, "
                        "possible sensor malfunction or fire risk"
                    )
                elif temperature < -15:
                    anomalies.append(
                        f"Temperature {temperature}°C — extreme cold, "
                        "possible frost damage or sensor malfunction"
                    )

        return anomalies
