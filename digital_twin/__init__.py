"""Digital twin domain package for farm-wide state, what-if simulation, and feedback."""

from digital_twin.calibration import CalibrationProfile, fit_soil_water_parameters, load_calibration_profile, save_calibration_profile
from digital_twin.contracts import FogSummaryContract, validate_fog_summary_payload
from digital_twin.entities import (
    ActuatorEntity,
    CropEntity,
    DecisionEntity,
    DigitalTwinEvent,
    FarmEntity,
    PolicyEntity,
    SensorEntity,
    SoilState,
    ZoneEntity,
)
from digital_twin.process_models import TwinStepContext, ZoneProcessModel
from digital_twin.simulator import DigitalTwinEngine, TwinStepResult, WhatIfResult
from digital_twin.synthetic_events import generate_rare_event_dataset, write_rare_event_dataset

__all__ = [
    "ActuatorEntity",
    "CalibrationProfile",
    "CropEntity",
    "DecisionEntity",
    "DigitalTwinEngine",
    "DigitalTwinEvent",
    "FarmEntity",
    "FogSummaryContract",
    "PolicyEntity",
    "SensorEntity",
    "SoilState",
    "TwinStepContext",
    "TwinStepResult",
    "WhatIfResult",
    "ZoneProcessModel",
    "ZoneEntity",
    "fit_soil_water_parameters",
    "generate_rare_event_dataset",
    "load_calibration_profile",
    "save_calibration_profile",
    "validate_fog_summary_payload",
    "write_rare_event_dataset",
]


