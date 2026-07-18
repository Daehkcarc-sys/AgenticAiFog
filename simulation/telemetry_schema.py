"""Canonical telemetry contract shared by edge, fog, simulation, and FL."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from models import CriticalityScenario


class SensorFault(str, Enum):
    NONE = "none"
    RANDOM_DROPOUT = "random_dropout"
    GRADUAL_DRIFT = "gradual_drift"
    BURST_LOSS = "burst_loss"
    STUCK_AT = "stuck_at"


class LinkState(str, Enum):
    TERRESTRIAL = "terrestrial"
    NTN = "ntn"
    OFFLINE = "offline"


ReadingValue = float | int | str | bool | None


@dataclass(frozen=True)
class TelemetryRecord:
    """Versioned telemetry message with separate event and fault truth.

    Environmental events describe the field state. Sensor faults describe
    measurement or transport reliability. Keeping them separate prevents a
    real drought or flood from being mislabeled as an untrustworthy sensor.
    """

    event_id: str
    device_id: str
    zone_id: str
    timestamp: datetime
    sequence_number: int
    readings: dict[str, ReadingValue]
    tinyml_class: str = CriticalityScenario.NORMAL.value
    tinyml_confidence: float = 1.0
    tinyml_model_version: str = "sim-v1"
    actuator_state: dict[str, ReadingValue] = field(default_factory=dict)
    link_state: LinkState = LinkState.TERRESTRIAL
    event_label: CriticalityScenario = CriticalityScenario.NORMAL
    sensor_fault_label: SensorFault = SensorFault.NONE
    delivered: bool = True
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.event_id or not self.device_id or not self.zone_id:
            raise ValueError("event_id, device_id, and zone_id are required")
        if self.sequence_number < 0:
            raise ValueError("sequence_number must be non-negative")
        if not 0.0 <= self.tinyml_confidence <= 1.0:
            raise ValueError("tinyml_confidence must be between 0 and 1")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.astimezone(timezone.utc).isoformat()
        payload["link_state"] = self.link_state.value
        payload["event_label"] = self.event_label.value
        payload["sensor_fault_label"] = self.sensor_fault_label.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TelemetryRecord":
        timestamp = payload["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return cls(
            event_id=str(payload["event_id"]),
            device_id=str(payload["device_id"]),
            zone_id=str(payload["zone_id"]),
            timestamp=timestamp,
            sequence_number=int(payload["sequence_number"]),
            readings=dict(payload.get("readings", {})),
            tinyml_class=str(
                payload.get("tinyml_class", CriticalityScenario.NORMAL.value)
            ),
            tinyml_confidence=float(payload.get("tinyml_confidence", 1.0)),
            tinyml_model_version=str(payload.get("tinyml_model_version", "sim-v1")),
            actuator_state=dict(payload.get("actuator_state", {})),
            link_state=LinkState(payload.get("link_state", LinkState.TERRESTRIAL)),
            event_label=CriticalityScenario(
                payload.get("event_label", CriticalityScenario.NORMAL.value)
            ),
            sensor_fault_label=SensorFault(
                payload.get("sensor_fault_label", SensorFault.NONE.value)
            ),
            delivered=bool(payload.get("delivered", True)),
            schema_version=str(payload.get("schema_version", "1.0")),
        )
