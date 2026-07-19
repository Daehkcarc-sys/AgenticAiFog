"""Lightweight zone-level checks that compare multiple sensor sources."""

from __future__ import annotations

from dataclasses import dataclass

from simulation.telemetry_schema import TelemetryRecord


@dataclass(frozen=True)
class AnomalyFinding:
    feature: str
    spread: float
    threshold: float
    reason: str


DEFAULT_SPREAD_THRESHOLDS: dict[str, float] = {
    "temperature": 8.0,
    "humidity": 20.0,
    "soil_moisture": 25.0,
    "ph": 1.5,
    "irrigation_flow": 15.0,
}


def cross_sensor_findings(
    records: list[TelemetryRecord],
    thresholds: dict[str, float] | None = None,
) -> list[AnomalyFinding]:
    """Compare the latest delivered reading from each device in one zone."""
    thresholds = thresholds or DEFAULT_SPREAD_THRESHOLDS
    latest_by_device: dict[str, TelemetryRecord] = {}
    for record in records:
        if not record.delivered:
            continue
        current = latest_by_device.get(record.device_id)
        if current is None or record.timestamp >= current.timestamp:
            latest_by_device[record.device_id] = record

    findings: list[AnomalyFinding] = []
    for feature, threshold in thresholds.items():
        values = [
            float(record.readings[feature])
            for record in latest_by_device.values()
            if isinstance(record.readings.get(feature), (int, float))
            and not isinstance(record.readings.get(feature), bool)
        ]
        if len(values) < 2:
            continue
        spread = max(values) - min(values)
        if spread > threshold:
            findings.append(
                AnomalyFinding(
                    feature=feature,
                    spread=spread,
                    threshold=threshold,
                    reason=(
                        f"Cross-sensor spread {spread:.2f} exceeds "
                        f"the {threshold:.2f} threshold"
                    ),
                )
            )
    return findings
