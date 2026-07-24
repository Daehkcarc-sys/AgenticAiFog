"""Domain entities for the agricultural digital twin."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class SoilState:
    moisture: float | None = None
    ph: float | None = None
    nitrogen: float | None = None
    phosphorus: float | None = None
    potassium: float | None = None
    salinity: float | None = None
    updated_at: str | None = None

    def update_from_readings(self, readings: dict[str, Any], timestamp: str) -> None:
        mapping = {
            "soil_moisture": "moisture",
            "ph": "ph",
            "nitrogen": "nitrogen",
            "phosphorus": "phosphorus",
            "potassium": "potassium",
            "salinity": "salinity",
        }
        for source, target in mapping.items():
            value = readings.get(source)
            if isinstance(value, (int, float)):
                setattr(self, target, float(value))
        self.updated_at = timestamp


@dataclass(slots=True)
class CropEntity:
    crop_id: str
    crop_type: str = "unknown"
    growth_stage: str = "unknown"
    disease_risk: float = 0.0
    pest_risk: float = 0.0
    heat_stress_risk: float = 0.0


@dataclass(slots=True)
class SensorEntity:
    sensor_id: str
    zone_id: str
    sensor_type: str = "soil_environment"
    trust_score: float | None = None
    last_seen: str | None = None
    last_readings: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActuatorEntity:
    actuator_id: str
    zone_id: str
    actuator_type: str
    state: str = "unknown"
    last_command: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class DecisionEntity:
    decision_id: str
    zone_id: str
    action: str | None
    source: str | None = None
    confidence: float | None = None
    result: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class PolicyEntity:
    policy_id: str
    version: int
    rules: dict[str, Any]
    active: bool = True
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class DigitalTwinEvent:
    event_id: str
    event_type: str
    zone_id: str
    sensor_id: str | None
    scenario: str | None
    severity: str | None
    critical: bool
    payload: dict[str, Any]
    created_at: str


@dataclass(slots=True)
class ZoneEntity:
    zone_id: str
    crop: CropEntity = field(default_factory=lambda: CropEntity("default-crop"))
    soil: SoilState = field(default_factory=SoilState)
    sensors: dict[str, SensorEntity] = field(default_factory=dict)
    actuators: dict[str, ActuatorEntity] = field(default_factory=dict)
    last_scenario: str | None = None
    last_severity: str | None = None
    last_decision: DecisionEntity | None = None
    risk_index: float = 0.0
    dynamic_state: dict[str, Any] = field(default_factory=dict)
    state_history: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str | None = None


@dataclass(slots=True)
class FarmEntity:
    farm_id: str
    zones: dict[str, ZoneEntity] = field(default_factory=dict)
    policies: dict[str, PolicyEntity] = field(default_factory=dict)
    events: list[DigitalTwinEvent] = field(default_factory=list)
    simulation_time: str | None = None
    simulation_step: int = 0

    def zone(self, zone_id: str) -> ZoneEntity:
        if zone_id not in self.zones:
            self.zones[zone_id] = ZoneEntity(zone_id=zone_id)
        return self.zones[zone_id]


