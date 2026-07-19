"""Context Layer - rolling history, features, and anomaly indicators.

The context layer enriches validated sensor readings before the intelligence
agents run.  It is intentionally deterministic and in-memory so it can run on a
fog node without network or database dependencies.
"""

from __future__ import annotations

from collections import defaultdict, deque
from statistics import mean, pvariance
from typing import Any

from config import OPTIONAL_FIELDS, REQUIRED_FIELDS
from models import ContextResult


class ContextManagerAgent:
    """Build temporal and semantic context from recent trusted readings.

    Maintains a bounded sliding window per sensor.  Each run returns:
    - rolling averages for numeric fields
    - simple slopes between the oldest and newest values
    - population variance for volatility estimation
    - derived farm features such as VPD and nutrient balance
    - anomaly indicators relative to recent history
    """

    def __init__(
        self,
        window_size: int = 10,
        anomaly_z_threshold: float = 2.5,
    ) -> None:
        if window_size < 2:
            raise ValueError("window_size must be at least 2")
        self._window_size = window_size
        self._anomaly_z_threshold = anomaly_z_threshold
        self._history: defaultdict[str, deque[dict[str, float]]] = defaultdict(
            lambda: deque(maxlen=self._window_size)
        )

    def run(
        self,
        sensor_id: str | None,
        raw_readings: dict[str, Any],
        tinyml_output: dict[str, Any] | None = None,
    ) -> ContextResult:
        numeric_readings = self._numeric_readings(raw_readings)
        history_key = sensor_id or "UNKNOWN"
        history = self._history[history_key]
        history.append(numeric_readings)

        rolling_averages = self._rolling_averages(history)
        trends = self._trends(history)
        variances = self._variances(history)
        derived_features = self._derived_features(raw_readings)
        anomaly_indicators = self._anomaly_indicators(
            numeric_readings=numeric_readings,
            rolling_averages=rolling_averages,
            variances=variances,
            tinyml_output=tinyml_output or {},
        )
        semantic_context = self._semantic_context(
            rolling_averages=rolling_averages,
            trends=trends,
            derived_features=derived_features,
            anomaly_indicators=anomaly_indicators,
            history=list(history),
        )

        return ContextResult(
            passed=True,
            history_count=len(history),
            rolling_averages=rolling_averages,
            trends=trends,
            variances=variances,
            derived_features=derived_features,
            anomaly_indicators=anomaly_indicators,
            semantic_context=semantic_context,
            reason=(
                f"Context built from {len(history)} reading"
                f"{'' if len(history) == 1 else 's'}"
            ),
        )

    def history_for_sensor(self, sensor_id: str | None) -> list[dict[str, float]]:
        """Return a copy of the current sliding window for a sensor."""
        return list(self._history[sensor_id or "UNKNOWN"])

    @staticmethod
    def _numeric_readings(raw_readings: dict[str, Any]) -> dict[str, float]:
        return {
            field: float(value)
            for field, value in raw_readings.items()
            if field in REQUIRED_FIELDS + OPTIONAL_FIELDS and isinstance(value, (int, float))
        }

    @staticmethod
    def _rolling_averages(history: deque[dict[str, float]]) -> dict[str, float]:
        averages: dict[str, float] = {}
        fields = {field for reading in history for field in reading}
        for field in fields:
            values = [reading[field] for reading in history if field in reading]
            if values:
                averages[field] = round(mean(values), 3)
        return averages

    @staticmethod
    def _trends(history: deque[dict[str, float]]) -> dict[str, float]:
        if len(history) < 2:
            return {}

        oldest = history[0]
        newest = history[-1]
        denominator = max(len(history) - 1, 1)
        trends: dict[str, float] = {}
        for field in newest.keys() & oldest.keys():
            trends[field] = round((newest[field] - oldest[field]) / denominator, 3)
        return trends

    @staticmethod
    def _variances(history: deque[dict[str, float]]) -> dict[str, float]:
        variances: dict[str, float] = {}
        fields = {field for reading in history for field in reading}
        for field in fields:
            values = [reading[field] for reading in history if field in reading]
            if len(values) >= 2:
                variances[field] = round(pvariance(values), 3)
            elif values:
                variances[field] = 0.0
        return variances

    @staticmethod
    def _derived_features(raw_readings: dict[str, Any]) -> dict[str, Any]:
        temperature = raw_readings.get("temperature")
        humidity = raw_readings.get("humidity")
        moisture = raw_readings.get("soil_moisture")
        nitrogen = raw_readings.get("nitrogen")
        phosphorus = raw_readings.get("phosphorus")
        potassium = raw_readings.get("potassium")

        features: dict[str, Any] = {}
        if isinstance(temperature, (int, float)) and isinstance(humidity, (int, float)):
            saturation_vapor_pressure = 0.6108 * (
                2.718281828 ** ((17.27 * temperature) / (temperature + 237.3))
            )
            actual_vapor_pressure = saturation_vapor_pressure * (humidity / 100)
            features["vapor_pressure_deficit_kpa"] = round(
                max(saturation_vapor_pressure - actual_vapor_pressure, 0.0), 3
            )
            features["heat_humidity_index"] = round(temperature + 0.1 * humidity, 3)

        if isinstance(moisture, (int, float)):
            if moisture < 20:
                band = "severe_deficit"
            elif moisture < 40:
                band = "moderate_deficit"
            elif moisture <= 70:
                band = "optimal"
            else:
                band = "excess"
            features["soil_moisture_band"] = band

        nutrients = [nitrogen, phosphorus, potassium]
        if all(isinstance(value, (int, float)) for value in nutrients):
            nutrient_values = [float(value) for value in nutrients]
            nutrient_avg = mean(nutrient_values)
            features["nutrient_balance_index"] = round(
                1.0
                - (
                    (max(nutrient_values) - min(nutrient_values))
                    / max(nutrient_avg, 1.0)
                ),
                3,
            )

        return features

    def _anomaly_indicators(
        self,
        numeric_readings: dict[str, float],
        rolling_averages: dict[str, float],
        variances: dict[str, float],
        tinyml_output: dict[str, Any],
    ) -> dict[str, Any]:
        z_scores: dict[str, float] = {}
        volatile_fields: list[str] = []

        for field, value in numeric_readings.items():
            variance = variances.get(field, 0.0)
            if variance <= 0:
                continue
            z_score = abs(value - rolling_averages.get(field, value)) / (variance ** 0.5)
            z_scores[field] = round(z_score, 3)
            if z_score >= self._anomaly_z_threshold:
                volatile_fields.append(field)

        return {
            "history_ready": len(rolling_averages) > 0,
            "z_scores": z_scores,
            "volatile_fields": volatile_fields,
            "tinyml_anomaly": bool(tinyml_output.get("anomaly_detected", False)),
            "anomaly_count": len(volatile_fields)
            + int(bool(tinyml_output.get("anomaly_detected", False))),
        }

    @staticmethod
    def _semantic_context(
        rolling_averages: dict[str, float],
        trends: dict[str, float],
        derived_features: dict[str, Any],
        anomaly_indicators: dict[str, Any],
        history: list[dict[str, float]],
    ) -> str:
        parts: list[str] = []
        moisture_band = derived_features.get("soil_moisture_band")
        if moisture_band:
            parts.append(f"soil moisture is {moisture_band}")

        moisture_trend = trends.get("soil_moisture")
        if moisture_trend is not None:
            direction = "rising" if moisture_trend > 0 else "falling" if moisture_trend < 0 else "stable"
            parts.append(
                f"soil moisture trend is {direction} "
                f"({moisture_trend:+.2f} percentage points per reading)"
            )
            moisture_values = [
                reading["soil_moisture"]
                for reading in history
                if "soil_moisture" in reading
            ]
            if len(moisture_values) >= 3:
                delta = moisture_values[-1] - moisture_values[0]
                parts.append(
                    f"soil moisture changed {delta:+.2f} over "
                    f"{len(moisture_values)} readings"
                )

        vpd = derived_features.get("vapor_pressure_deficit_kpa")
        if isinstance(vpd, (int, float)):
            if vpd >= 2.0:
                parts.append("evaporative demand is high")
            elif vpd <= 0.4:
                parts.append("disease pressure may increase under humid air")

        volatile_fields = anomaly_indicators.get("volatile_fields", [])
        if volatile_fields:
            parts.append(f"volatile fields: {', '.join(volatile_fields)}")

        if len(history) >= 3:
            parts.append(f"condition persisted for {len(history)} trusted readings")

        if not parts and rolling_averages:
            parts.append("recent conditions are stable")
        return "; ".join(parts) if parts else "insufficient historical context"
