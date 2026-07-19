"""Dependency-free rolling statistics and agricultural derived features."""

from __future__ import annotations

import math
import statistics
from datetime import datetime

from simulation.telemetry_schema import TelemetryRecord


def numeric_feature_series(
    records: list[TelemetryRecord],
) -> dict[str, list[tuple[datetime, float]]]:
    series: dict[str, list[tuple[datetime, float]]] = {}
    for record in records:
        for name, value in record.readings.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            series.setdefault(name, []).append((record.timestamp, float(value)))
    return series


def linear_slope_per_hour(points: list[tuple[datetime, float]]) -> float:
    """Return an ordinary-least-squares slope in feature units per hour."""
    if len(points) < 2:
        return 0.0
    origin = min(timestamp for timestamp, _ in points)
    x = [(timestamp - origin).total_seconds() / 3600.0 for timestamp, _ in points]
    y = [value for _, value in points]
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(y)
    denominator = sum((value - x_mean) ** 2 for value in x)
    if denominator == 0:
        return 0.0
    numerator = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x, y)
    )
    return numerator / denominator


def summarize_numeric_features(
    records: list[TelemetryRecord],
) -> dict[str, dict[str, float]]:
    summaries: dict[str, dict[str, float]] = {}
    for name, points in numeric_feature_series(records).items():
        values = [value for _, value in points]
        summaries[name] = {
            "mean": statistics.mean(values),
            "minimum": min(values),
            "maximum": max(values),
            "latest": points[-1][1],
            "slope_per_hour": linear_slope_per_hour(points),
        }
    return summaries


def derived_agricultural_features(
    summaries: dict[str, dict[str, float]],
) -> dict[str, float]:
    derived: dict[str, float] = {}
    moisture = summaries.get("soil_moisture", {}).get("mean")
    temperature = summaries.get("temperature", {}).get("mean")
    humidity = summaries.get("humidity", {}).get("mean")

    if moisture is not None:
        derived["soil_water_deficit"] = max(0.0, 40.0 - moisture)

    if temperature is not None and humidity is not None:
        saturation_vapor_pressure = 0.6108 * math.exp(
            (17.27 * temperature) / (temperature + 237.3)
        )
        derived["vapor_pressure_deficit_kpa"] = saturation_vapor_pressure * (
            1.0 - humidity / 100.0
        )

    return derived
