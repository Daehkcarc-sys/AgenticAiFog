"""In-memory farm digital twin engine, time-step evolution, and what-if simulation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from digital_twin.calibration import CalibrationProfile
from digital_twin.contracts import FogSummaryContract
from digital_twin.entities import (
    DecisionEntity,
    DigitalTwinEvent,
    FarmEntity,
    SensorEntity,
    ZoneEntity,
)
from digital_twin.process_models import (
    CropRiskModel,
    EquipmentDegradationModel,
    SoilWaterBalanceModel,
    TwinStepContext,
    ZoneProcessModel,
)

SEVERITY_WEIGHT = {None: 0.0, "low": 0.2, "medium": 0.55, "high": 0.85}
SCENARIO_WEIGHT = {
    None: 0.0,
    "Normal": 0.0,
    "Water deficit": 0.65,
    "Flooding": 0.85,
    "Fire or heat stress": 0.9,
    "Crop disease risk": 0.7,
    "Pest infestation": 0.6,
    "Soil degradation": 0.7,
    "Equipment failure": 0.95,
}


@dataclass(frozen=True, slots=True)
class WhatIfResult:
    scenario: str
    zone_id: str
    baseline_risk: float
    projected_risk: float
    delta: float
    recommendation: str
    projected_state: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TwinStepResult:
    step: int
    simulation_time: str
    minutes: int
    zones: dict[str, dict[str, Any]]


class DigitalTwinEngine:
    """Digital twin engine with replaceable process models.

    The default process models are deterministic and lightweight. Teammates can
    replace them with calibrated agronomic, hydraulic, or ML models as long as
    each model implements `step(zone, context) -> dict`.
    """

    def __init__(
        self,
        farm_id: str = "demo-farm",
        process_models: Iterable[ZoneProcessModel] | None = None,
        calibration: CalibrationProfile | None = None,
    ) -> None:
        self.farm = FarmEntity(farm_id=farm_id)
        self.calibration = calibration or CalibrationProfile(farm_id=farm_id)
        self.process_models = list(process_models) if process_models is not None else self._default_process_models(self.calibration)

    def apply_fog_summary(
        self,
        payload: dict[str, Any],
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> DigitalTwinEvent:
        summary = FogSummaryContract.from_payload(payload)
        now = created_at or datetime.now(timezone.utc).isoformat()
        event = DigitalTwinEvent(
            event_id=event_id or f"summary-{len(self.farm.events) + 1}",
            event_type="fog_summary",
            zone_id=summary.zone_id,
            sensor_id=summary.sensor_id,
            scenario=summary.scenario,
            severity=summary.severity,
            critical=summary.critical,
            payload=summary.to_payload(),
            created_at=now,
        )
        zone = self.farm.zone(summary.zone_id)
        zone.last_scenario = summary.scenario
        zone.last_severity = summary.severity
        zone.updated_at = now
        if summary.raw_readings:
            zone.soil.update_from_readings(summary.raw_readings, now)
            zone.dynamic_state["last_raw_readings"] = summary.raw_readings
        sensor = zone.sensors.get(summary.sensor_id) or SensorEntity(summary.sensor_id, summary.zone_id)
        sensor.trust_score = summary.trust_score
        sensor.last_seen = now
        sensor.last_readings = summary.raw_readings or sensor.last_readings
        zone.sensors[summary.sensor_id] = sensor
        zone.last_decision = DecisionEntity(
            decision_id=f"decision-{event.event_id}",
            zone_id=summary.zone_id,
            action=summary.decision,
            source=summary.decision_source,
            confidence=summary.confidence,
            result=summary.result,
            created_at=now,
        )
        zone.risk_index = self._risk_index(summary.scenario, summary.severity, summary.critical, summary.trust_score)
        self._snapshot(zone, now, reason="fog_summary")
        self.farm.events.append(event)
        if self.farm.simulation_time is None:
            self.farm.simulation_time = now
        return event

    def step(
        self,
        minutes: int = 10,
        weather: dict[str, float] | None = None,
        interventions: dict[str, str] | None = None,
    ) -> TwinStepResult:
        if minutes < 1:
            raise ValueError("minutes must be positive")
        current_time = self._current_time()
        next_time = current_time + timedelta(minutes=minutes)
        context = TwinStepContext(
            minutes=minutes,
            weather=weather or {},
            interventions=interventions or {},
        )
        self.farm.simulation_step += 1
        self.farm.simulation_time = next_time.isoformat()
        zone_traces: dict[str, dict[str, Any]] = {}
        for zone in self.farm.zones.values():
            model_traces = [model.step(zone, context) for model in self.process_models]
            zone.risk_index = self._dynamic_risk(zone)
            zone.updated_at = self.farm.simulation_time
            self._snapshot(zone, self.farm.simulation_time, reason="simulation_step")
            zone_traces[zone.zone_id] = {
                "risk_index": zone.risk_index,
                "soil_moisture": zone.soil.moisture,
                "crop_risks": {
                    "disease": zone.crop.disease_risk,
                    "heat_stress": zone.crop.heat_stress_risk,
                    "pest": zone.crop.pest_risk,
                },
                "dynamic_state": dict(zone.dynamic_state),
                "models": model_traces,
            }
        return TwinStepResult(
            step=self.farm.simulation_step,
            simulation_time=self.farm.simulation_time,
            minutes=minutes,
            zones=zone_traces,
        )

    def simulate(
        self,
        steps: int,
        minutes_per_step: int = 10,
        weather_series: list[dict[str, float]] | None = None,
        interventions: dict[str, str] | None = None,
    ) -> list[TwinStepResult]:
        if steps < 1:
            raise ValueError("steps must be positive")
        results = []
        for index in range(steps):
            weather = weather_series[index] if weather_series and index < len(weather_series) else None
            results.append(self.step(minutes_per_step, weather=weather, interventions=interventions))
        return results

    def what_if(self, zone_id: str, scenario: str, intervention: str | None = None, horizon_steps: int = 3) -> WhatIfResult:
        clone = deepcopy(self)
        zone = clone.farm.zone(zone_id)
        baseline = zone.risk_index
        intervention = intervention or self._default_intervention(scenario)
        weather = self._scenario_weather(scenario)
        step_results = clone.simulate(
            steps=max(1, horizon_steps),
            minutes_per_step=30,
            weather_series=[weather] * max(1, horizon_steps),
            interventions={zone_id: intervention},
        )
        projected_zone = clone.farm.zone(zone_id)
        projected = projected_zone.risk_index
        return WhatIfResult(
            scenario=scenario,
            zone_id=zone_id,
            baseline_risk=round(min(1.0, baseline), 3),
            projected_risk=round(min(1.0, projected), 3),
            delta=round(projected - baseline, 3),
            recommendation=self._recommendation(scenario, intervention, projected_zone),
            projected_state=self._zone_state(projected_zone),
            assumptions=[
                "Dynamic-ready deterministic process models; replaceable with calibrated farm models.",
                f"Horizon: {max(1, horizon_steps)} steps of 30 minutes.",
            ],
            trace=[result.zones.get(zone_id, {}) for result in step_results],
        )

    def dashboard_state(self) -> dict[str, Any]:
        return {
            "farm_id": self.farm.farm_id,
            "simulation_time": self.farm.simulation_time,
            "simulation_step": self.farm.simulation_step,
            "calibration": self.calibration.to_dict(),
            "process_models": [getattr(model, "name", model.__class__.__name__) for model in self.process_models],
            "zones": [self._zone_state(zone) for zone in self.farm.zones.values()],
            "event_count": len(self.farm.events),
        }

    def apply_calibration(self, calibration: CalibrationProfile) -> None:
        self.calibration = calibration
        self.process_models = self._default_process_models(calibration)

    def register_process_model(self, model: ZoneProcessModel) -> None:
        self.process_models.append(model)

    def replace_process_models(self, models: Iterable[ZoneProcessModel]) -> None:
        self.process_models = list(models)

    @staticmethod
    def _default_process_models(calibration: CalibrationProfile) -> list[ZoneProcessModel]:
        return [
            SoilWaterBalanceModel(calibration.soil_water),
            CropRiskModel(calibration.crop_risk),
            EquipmentDegradationModel(calibration.equipment),
        ]

    def _current_time(self) -> datetime:
        if self.farm.simulation_time:
            return datetime.fromisoformat(self.farm.simulation_time)
        now = datetime.now(timezone.utc)
        self.farm.simulation_time = now.isoformat()
        return now

    def _snapshot(self, zone: ZoneEntity, timestamp: str, reason: str) -> None:
        zone.state_history.append({"timestamp": timestamp, "reason": reason, **self._zone_state(zone)})
        if len(zone.state_history) > 500:
            del zone.state_history[:-500]

    def _zone_state(self, zone: ZoneEntity) -> dict[str, Any]:
        return {
            "zone_id": zone.zone_id,
            "risk_index": zone.risk_index,
            "last_scenario": zone.last_scenario,
            "last_severity": zone.last_severity,
            "soil": {
                "moisture": zone.soil.moisture,
                "ph": zone.soil.ph,
                "nitrogen": zone.soil.nitrogen,
                "phosphorus": zone.soil.phosphorus,
                "potassium": zone.soil.potassium,
                "salinity": zone.soil.salinity,
            },
            "crop": {
                "crop_type": zone.crop.crop_type,
                "growth_stage": zone.crop.growth_stage,
                "disease_risk": zone.crop.disease_risk,
                "heat_stress_risk": zone.crop.heat_stress_risk,
                "pest_risk": zone.crop.pest_risk,
            },
            "dynamic_state": dict(zone.dynamic_state),
            "history_length": len(zone.state_history),
            "sensors": sorted(zone.sensors),
            "last_decision": None if zone.last_decision is None else {
                "action": zone.last_decision.action,
                "source": zone.last_decision.source,
                "confidence": zone.last_decision.confidence,
                "result": zone.last_decision.result,
            },
        }

    @staticmethod
    def _risk_index(scenario: str | None, severity: str | None, critical: bool, trust_score: float | None) -> float:
        scenario_weight = SCENARIO_WEIGHT.get(scenario, 0.5)
        severity_weight = SEVERITY_WEIGHT.get(severity, 0.4)
        trust_penalty = 0.0 if trust_score is None else max(0.0, 0.75 - trust_score) * 0.4
        critical_boost = 0.15 if critical else 0.0
        return round(min(1.0, scenario_weight * 0.55 + severity_weight * 0.3 + trust_penalty + critical_boost), 3)

    @staticmethod
    def _dynamic_risk(zone: ZoneEntity) -> float:
        moisture = zone.soil.moisture if zone.soil.moisture is not None else 45.0
        dry_risk = max(0.0, (35.0 - moisture) / 35.0)
        flood_risk = max(0.0, (moisture - 80.0) / 20.0)
        equipment_risk = float(zone.dynamic_state.get("equipment_risk", 0.0))
        crop_risk = max(zone.crop.disease_risk, zone.crop.heat_stress_risk, zone.crop.pest_risk)
        scenario_memory = SCENARIO_WEIGHT.get(zone.last_scenario, 0.0) * 0.2
        return round(min(1.0, max(dry_risk, flood_risk) * 0.35 + crop_risk * 0.3 + equipment_risk * 0.2 + scenario_memory), 3)

    @staticmethod
    def _default_intervention(scenario: str) -> str:
        return {
            "irrigation": "irrigate",
            "disease_risk": "reduce_humidity",
            "heat_stress": "cooling_irrigation",
            "equipment_failure": "dispatch_maintenance",
            "resource_allocation": "prioritize_high_risk_zones",
        }.get(scenario, "manual_review")

    @staticmethod
    def _scenario_weather(scenario: str) -> dict[str, float]:
        return {
            "irrigation": {"temperature": 33.0, "humidity": 35.0, "rainfall": 0.0},
            "disease_risk": {"temperature": 25.0, "humidity": 92.0, "rainfall": 4.0},
            "heat_stress": {"temperature": 42.0, "humidity": 22.0, "rainfall": 0.0},
            "equipment_failure": {"temperature": 28.0, "humidity": 55.0, "rainfall": 0.0},
            "resource_allocation": {"temperature": 31.0, "humidity": 45.0, "rainfall": 0.0},
        }.get(scenario, {"temperature": 25.0, "humidity": 60.0, "rainfall": 0.0})

    @staticmethod
    def _recommendation(scenario: str, intervention: str, zone: ZoneEntity) -> str:
        if scenario == "irrigation" and (zone.soil.moisture or 0.0) >= 35.0:
            return "monitor_after_irrigation"
        if scenario == "equipment_failure" and zone.dynamic_state.get("equipment_risk", 1.0) < 0.4:
            return "maintenance_reduced_risk"
        return intervention



