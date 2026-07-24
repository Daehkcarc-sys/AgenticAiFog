"""Calibration data structures and fitting helpers for digital twin models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from statistics import mean
from typing import Any


@dataclass(frozen=True, slots=True)
class SoilWaterParameters:
    rainfall_infiltration: float = 0.22
    irrigation_gain: float = 10.0
    evapotranspiration_coefficient: float = 0.08
    drainage_threshold: float = 85.0
    drainage_coefficient: float = 0.18


@dataclass(frozen=True, slots=True)
class CropRiskParameters:
    disease_memory: float = 0.75
    disease_humidity_threshold: float = 75.0
    heat_memory: float = 0.65
    heat_temperature_threshold: float = 32.0
    pest_memory: float = 0.80
    pest_temperature_reference: float = 20.0
    pest_humidity_reference: float = 65.0


@dataclass(frozen=True, slots=True)
class EquipmentParameters:
    base_risk: float = 0.05
    hourly_degradation: float = 0.005
    fault_risk_boost: float = 0.15
    maintenance_reduction: float = 0.35


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    schema_version: str = "1.0"
    farm_id: str = "demo-farm"
    source: str = "default_parameters"
    soil_water: SoilWaterParameters = field(default_factory=SoilWaterParameters)
    crop_risk: CropRiskParameters = field(default_factory=CropRiskParameters)
    equipment: EquipmentParameters = field(default_factory=EquipmentParameters)
    metrics: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=lambda: [
        "Default profile is not real farm calibration.",
        "Use fit_soil_water_parameters with measured before/after moisture data.",
    ])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalibrationProfile":
        return cls(
            schema_version=str(data.get("schema_version", "1.0")),
            farm_id=str(data.get("farm_id", "demo-farm")),
            source=str(data.get("source", "loaded_profile")),
            soil_water=SoilWaterParameters(**data.get("soil_water", {})),
            crop_risk=CropRiskParameters(**data.get("crop_risk", {})),
            equipment=EquipmentParameters(**data.get("equipment", {})),
            metrics=dict(data.get("metrics", {})),
            caveats=list(data.get("caveats", [])),
        )


def save_calibration_profile(profile: CalibrationProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")


def load_calibration_profile(path: Path) -> CalibrationProfile:
    return CalibrationProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))


def fit_soil_water_parameters(records: list[dict[str, Any]], farm_id: str = "demo-farm") -> CalibrationProfile:
    """Fit simple soil-water coefficients from measured step records.

    Required per record:
    - before_moisture
    - after_moisture
    - minutes

    Optional per record:
    - rainfall
    - irrigated: bool
    - temperature
    - humidity

    This is intentionally conservative: it estimates coefficients from observed
    averages, then clamps them to physically plausible ranges for this lightweight
    model. It is a calibration hook, not a replacement for agronomic validation.
    """
    usable = [row for row in records if _has_numbers(row, "before_moisture", "after_moisture", "minutes")]
    if not usable:
        raise ValueError("calibration requires measured before/after moisture records")

    rainfall_samples = []
    irrigation_samples = []
    evap_samples = []
    for row in usable:
        before = float(row["before_moisture"])
        after = float(row["after_moisture"])
        minutes = max(1.0, float(row["minutes"]))
        rainfall = max(0.0, float(row.get("rainfall", 0.0) or 0.0))
        irrigated = bool(row.get("irrigated", False))
        temperature = float(row.get("temperature", 25.0) or 25.0)
        humidity = min(100.0, max(0.0, float(row.get("humidity", 60.0) or 60.0)))
        delta = after - before
        atmospheric_demand = max(0.01, (temperature - 18.0) * (1.0 - humidity / 100.0) * minutes / 60.0)
        if rainfall > 0 and not irrigated and delta > 0:
            rainfall_samples.append(delta / rainfall)
        if irrigated and delta > 0:
            irrigation_samples.append(delta)
        if delta < 0:
            evap_samples.append(abs(delta) / atmospheric_demand)

    soil = SoilWaterParameters(
        rainfall_infiltration=_clamp(mean(rainfall_samples) if rainfall_samples else 0.22, 0.05, 0.80),
        irrigation_gain=_clamp(mean(irrigation_samples) if irrigation_samples else 10.0, 1.0, 35.0),
        evapotranspiration_coefficient=_clamp(mean(evap_samples) if evap_samples else 0.08, 0.01, 0.40),
    )
    metrics = {
        "records_used": len(usable),
        "rainfall_samples": len(rainfall_samples),
        "irrigation_samples": len(irrigation_samples),
        "evap_samples": len(evap_samples),
    }
    return CalibrationProfile(
        farm_id=farm_id,
        source="fit_soil_water_parameters",
        soil_water=soil,
        metrics=metrics,
        caveats=[
            "Soil-water parameters fitted from supplied measurements.",
            "Crop and equipment parameters remain defaults unless separately calibrated.",
            "Validate against held-out farm observations before claiming real accuracy.",
        ],
    )


def _has_numbers(row: dict[str, Any], *fields: str) -> bool:
    return all(isinstance(row.get(field), (int, float)) for field in fields)


def _clamp(value: float, lower: float, upper: float) -> float:
    return round(min(upper, max(lower, float(value))), 4)
