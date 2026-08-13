"""Adapter between TelemetryRecord and the FogPipeline dict contract.

This is the integration bridge described in item 1 of the main missing work
list: a function that converts the canonical simulation telemetry schema into
the sensor_data dict that FogPipeline.run() expects.

Extra fields (zone_id, link_state, fault label, event label) are carried
through so the ZoneFogPipeline and NTN-aware routing can use them.
"""

from __future__ import annotations

from models import CriticalityScenario
from simulation.telemetry_schema import SensorFault, TelemetryRecord

# Map TinyML classification output to a pipeline-whitelisted action.
# WATER_DEFICIT → irrigate; FLOODING → stop; everything abnormal → alert.
_SCENARIO_TO_ACTION: dict[str, str] = {
    CriticalityScenario.WATER_DEFICIT.value:     "irrigate",
    CriticalityScenario.FLOODING.value:          "stop_irrigation",
    CriticalityScenario.HEAT_STRESS.value:       "trigger_alert",
    CriticalityScenario.DISEASE_RISK.value:      "trigger_alert",
    CriticalityScenario.PEST_INFESTATION.value:  "trigger_alert",
    CriticalityScenario.SOIL_DEGRADATION.value:  "trigger_alert",
    CriticalityScenario.EQUIPMENT_FAILURE.value: "trigger_alert",
    CriticalityScenario.NORMAL.value:            "no_action",
}


def telemetry_to_pipeline_message(record: TelemetryRecord) -> dict:
    """Convert a TelemetryRecord to the dict format expected by FogPipeline.run().

    The pipeline gates on sensor_id against the SensorRegistry, so device_id
    must match a registered identity (e.g. "SENSOR_001"). Simulation device IDs
    use the pattern "zone-N-sensor-M" which won't pass the default registry;
    callers running through the real pipeline need to register those IDs or
    override sensor_id to a registered value.

    The message carries zone_id and link_state as extra keys so
    ZoneFogPipeline can enrich it with zone context before forwarding.
    """
    recommended_action = _SCENARIO_TO_ACTION.get(record.tinyml_class, "no_action")
    fault = record.sensor_fault_label
    anomaly_detected = fault is not SensorFault.NONE

    return {
        "sensor_id": record.device_id,
        "timestamp": record.timestamp.isoformat(),
        "raw_readings": {
            key: value
            for key, value in record.readings.items()
            if value is not None
        },
        "tinyml_output": {
            "recommended_action": recommended_action,
            "confidence": record.tinyml_confidence,
            "anomaly_detected": anomaly_detected,
        },
        # Pass-through context consumed by ZoneFogPipeline and NTN routing
        "zone_id": record.zone_id,
        "link_state": record.link_state.value,
        "sensor_fault_label": fault.value,
        "event_label": record.event_label.value,
        "sequence_number": record.sequence_number,
        "tinyml_class": record.tinyml_class,
        "tinyml_model_version": record.tinyml_model_version,
        "delivered": record.delivered,
    }


def action_for_scenario(scenario: str) -> str:
    """Return the whitelisted action for a given criticality scenario name."""
    return _SCENARIO_TO_ACTION.get(scenario, "no_action")
