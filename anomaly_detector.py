"""Context Layer - multi-level anomaly detection."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import median
from typing import Any

from config import VALID_RANGES


@dataclass
class AnomalyReport:
    passed: bool
    physical: list[str]
    statistical: list[str]
    domain: list[str]
    severity: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiLevelAnomalyDetector:
    """Detect physical, statistical, and domain anomalies."""

    def __init__(self, z_threshold: float = 2.5, iqr_multiplier: float = 1.5) -> None:
        self.z_threshold = z_threshold
        self.iqr_multiplier = iqr_multiplier

    def run(
        self,
        raw_readings: dict[str, Any],
        history: list[dict[str, float]],
        context: dict[str, Any],
    ) -> AnomalyReport:
        physical = self._physical(raw_readings)
        statistical = self._statistical(raw_readings, history)
        domain = self._domain(raw_readings, context)

        total = len(physical) + len(statistical) + len(domain)
        severity = "low"
        if physical or total >= 3:
            severity = "high"
        elif statistical or domain:
            severity = "medium"

        score = max(0.0, round(1.0 - min(total, 5) * 0.2, 3))
        return AnomalyReport(
            passed=not physical,
            physical=physical,
            statistical=statistical,
            domain=domain,
            severity=severity,
            score=score,
        )

    @staticmethod
    def _physical(raw_readings: dict[str, Any]) -> list[str]:
        findings: list[str] = []
        for field, (min_val, max_val) in VALID_RANGES.items():
            value = raw_readings.get(field)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                findings.append(f"{field}: non-numeric")
            elif value < min_val or value > max_val:
                findings.append(f"{field}: outside physical range [{min_val}, {max_val}]")
        return findings

    def _statistical(
        self,
        raw_readings: dict[str, Any],
        history: list[dict[str, float]],
    ) -> list[str]:
        findings: list[str] = []
        if len(history) < 4:
            return findings

        for field, value in raw_readings.items():
            if not isinstance(value, (int, float)):
                continue
            values = [reading[field] for reading in history if field in reading]
            if len(values) < 4:
                continue

            avg = sum(values) / len(values)
            variance = sum((x - avg) ** 2 for x in values) / len(values)
            if variance > 0:
                z_score = abs(value - avg) / (variance ** 0.5)
                if z_score >= self.z_threshold:
                    findings.append(f"{field}: z-score {z_score:.2f}")

            q1, q3 = self._quartiles(values)
            iqr = q3 - q1
            if iqr > 0:
                low = q1 - self.iqr_multiplier * iqr
                high = q3 + self.iqr_multiplier * iqr
                if value < low or value > high:
                    findings.append(f"{field}: outside IQR band [{low:.2f}, {high:.2f}]")

        return findings

    @staticmethod
    def _quartiles(values: list[float]) -> tuple[float, float]:
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        lower = ordered[:midpoint]
        upper = ordered[midpoint:] if len(ordered) % 2 == 0 else ordered[midpoint + 1 :]
        return median(lower), median(upper)

    @staticmethod
    def _domain(raw_readings: dict[str, Any], context: dict[str, Any]) -> list[str]:
        findings: list[str] = []
        moisture = raw_readings.get("soil_moisture")
        rainfall = raw_readings.get("rainfall")
        humidity = raw_readings.get("humidity")
        temperature = raw_readings.get("temperature")
        ph = raw_readings.get("ph")
        features = context.get("derived_features", {})
        vpd = features.get("vapor_pressure_deficit_kpa")

        if isinstance(moisture, (int, float)) and isinstance(rainfall, (int, float)):
            if moisture > 80 and rainfall > 50:
                findings.append("flooding risk: high moisture with heavy rainfall")
            if moisture < 20 and rainfall == 0:
                findings.append("drought risk: low moisture with no rainfall")

        if isinstance(humidity, (int, float)) and isinstance(temperature, (int, float)):
            if humidity > 85 and 18 <= temperature <= 32:
                findings.append("crop disease risk: warm humid conditions")
            if temperature > 38 and humidity < 35:
                findings.append("heat stress risk: hot dry conditions")

        if isinstance(ph, (int, float)) and (ph < 5.5 or ph > 8.0):
            findings.append("soil degradation risk: pH outside crop comfort band")

        if isinstance(vpd, (int, float)) and vpd >= 2.0:
            findings.append("high evaporative demand")

        return findings
