"""Pluggable process models for digital twin time-step evolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from digital_twin.calibration import CropRiskParameters, EquipmentParameters, SoilWaterParameters
from digital_twin.entities import ZoneEntity


@dataclass(frozen=True, slots=True)
class TwinStepContext:
    minutes: int
    weather: dict[str, float] = field(default_factory=dict)
    interventions: dict[str, str] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)


class ZoneProcessModel(Protocol):
    name: str

    def step(self, zone: ZoneEntity, context: TwinStepContext) -> dict[str, Any]:
        """Mutate one zone for a time step and return trace details."""


class SoilWaterBalanceModel:
    name = "soil_water_balance_v1"

    def __init__(self, parameters: SoilWaterParameters | None = None) -> None:
        self.parameters = parameters or SoilWaterParameters()

    def step(self, zone: ZoneEntity, context: TwinStepContext) -> dict[str, Any]:
        p = self.parameters
        moisture = zone.soil.moisture if zone.soil.moisture is not None else 45.0
        rainfall = float(context.weather.get("rainfall", 0.0))
        temperature = float(context.weather.get("temperature", 25.0))
        humidity = float(context.weather.get("humidity", 60.0))
        evap_rate = max(0.0, (temperature - 18.0) * (1.0 - min(100.0, humidity) / 100.0) * p.evapotranspiration_coefficient)
        evap_loss = evap_rate * context.minutes / 60.0
        rainfall_gain = rainfall * p.rainfall_infiltration
        intervention = context.interventions.get(zone.zone_id)
        irrigation_gain = p.irrigation_gain if intervention in {"irrigate", "increase_irrigation", "cooling_irrigation"} else 0.0
        drainage_loss = max(0.0, moisture + rainfall_gain + irrigation_gain - p.drainage_threshold) * p.drainage_coefficient
        updated = min(100.0, max(0.0, moisture + rainfall_gain + irrigation_gain - evap_loss - drainage_loss))
        zone.soil.moisture = round(updated, 3)
        return {
            "model": self.name,
            "calibrated_parameters": asdict(p),
            "previous_moisture": round(moisture, 3),
            "rainfall_gain": round(rainfall_gain, 3),
            "irrigation_gain": round(irrigation_gain, 3),
            "evap_loss": round(evap_loss, 3),
            "drainage_loss": round(drainage_loss, 3),
            "new_moisture": zone.soil.moisture,
        }


class CropRiskModel:
    name = "crop_risk_v1"

    def __init__(self, parameters: CropRiskParameters | None = None) -> None:
        self.parameters = parameters or CropRiskParameters()

    def step(self, zone: ZoneEntity, context: TwinStepContext) -> dict[str, Any]:
        p = self.parameters
        temperature = float(context.weather.get("temperature", 25.0))
        humidity = float(context.weather.get("humidity", 60.0))
        moisture = zone.soil.moisture if zone.soil.moisture is not None else 45.0
        salinity = zone.soil.salinity if zone.soil.salinity is not None else 1.0
        leaf_wetness_factor = max(0.0, (humidity - p.disease_humidity_threshold) / max(1.0, 100.0 - p.disease_humidity_threshold))
        heat_factor = max(0.0, (temperature - p.heat_temperature_threshold) / 14.0)
        pest_factor = max(0.0, (temperature - p.pest_temperature_reference) / 18.0) * max(0.0, 1.0 - abs(humidity - p.pest_humidity_reference) / 45.0)
        soil_stress = max(0.0, (25.0 - moisture) / 25.0) + max(0.0, (salinity - 3.0) / 4.0)
        zone.crop.disease_risk = round(min(1.0, zone.crop.disease_risk * p.disease_memory + leaf_wetness_factor * (1.0 - p.disease_memory)), 3)
        zone.crop.heat_stress_risk = round(min(1.0, zone.crop.heat_stress_risk * p.heat_memory + heat_factor * (1.0 - p.heat_memory) + soil_stress * 0.1), 3)
        zone.crop.pest_risk = round(min(1.0, zone.crop.pest_risk * p.pest_memory + pest_factor * (1.0 - p.pest_memory)), 3)
        return {
            "model": self.name,
            "calibrated_parameters": asdict(p),
            "disease_risk": zone.crop.disease_risk,
            "heat_stress_risk": zone.crop.heat_stress_risk,
            "pest_risk": zone.crop.pest_risk,
            "soil_stress": round(soil_stress, 3),
        }


class EquipmentDegradationModel:
    name = "equipment_degradation_v1"

    def __init__(self, parameters: EquipmentParameters | None = None) -> None:
        self.parameters = parameters or EquipmentParameters()

    def step(self, zone: ZoneEntity, context: TwinStepContext) -> dict[str, Any]:
        p = self.parameters
        intervention = context.interventions.get(zone.zone_id)
        equipment_risk = zone.dynamic_state.get("equipment_risk", p.base_risk)
        if intervention == "dispatch_maintenance":
            equipment_risk = max(0.0, equipment_risk - p.maintenance_reduction)
        else:
            equipment_risk = min(1.0, equipment_risk + context.minutes / 60.0 * p.hourly_degradation)
            if zone.last_scenario == "Equipment failure":
                equipment_risk = min(1.0, equipment_risk + p.fault_risk_boost)
        zone.dynamic_state["equipment_risk"] = round(equipment_risk, 3)
        return {
            "model": self.name,
            "calibrated_parameters": asdict(p),
            "equipment_risk": zone.dynamic_state["equipment_risk"],
        }

