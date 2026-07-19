"""Rolling, delivered-data context for a physical agricultural zone."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from context.anomaly_detection import cross_sensor_findings
from context.rolling_features import (
    derived_agricultural_features,
    summarize_numeric_features,
)
from simulation.telemetry_schema import TelemetryRecord


@dataclass(frozen=True)
class ZoneContext:
    zone_id: str
    window_start: datetime
    window_end: datetime
    record_count: int
    device_count: int
    feature_summaries: dict[str, dict[str, float]]
    derived_features: dict[str, float]
    anomaly_findings: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "record_count": self.record_count,
            "device_count": self.device_count,
            "feature_summaries": self.feature_summaries,
            "derived_features": self.derived_features,
            "anomaly_findings": self.anomaly_findings,
        }


class ZoneContextManager:
    """Maintain a bounded rolling window for each zone."""

    def __init__(self, max_records_per_zone: int = 256) -> None:
        if max_records_per_zone < 1:
            raise ValueError("max_records_per_zone must be positive")
        self._max_records = max_records_per_zone
        self._records: defaultdict[str, deque[TelemetryRecord]] = defaultdict(
            lambda: deque(maxlen=self._max_records)
        )

    def add(self, record: TelemetryRecord) -> bool:
        """Add a delivered record; return False for simulated packet loss."""
        if not record.delivered:
            return False
        zone_records = self._records[record.zone_id]
        if zone_records and record.timestamp < zone_records[-1].timestamp:
            raise ValueError("zone records must arrive in timestamp order")
        zone_records.append(record)
        return True

    def records(self, zone_id: str) -> list[TelemetryRecord]:
        return list(self._records.get(zone_id, ()))

    def snapshot(self, zone_id: str) -> ZoneContext:
        records = self.records(zone_id)
        if not records:
            raise KeyError(f"No delivered records for zone {zone_id}")
        summaries = summarize_numeric_features(records)
        findings = cross_sensor_findings(records)
        return ZoneContext(
            zone_id=zone_id,
            window_start=records[0].timestamp,
            window_end=records[-1].timestamp,
            record_count=len(records),
            device_count=len({record.device_id for record in records}),
            feature_summaries=summaries,
            derived_features=derived_agricultural_features(summaries),
            anomaly_findings=[finding.__dict__ for finding in findings],
        )
