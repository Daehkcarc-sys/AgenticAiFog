"""Synthetic rare/extreme event data for ML and digital twin validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import CriticalityScenario
from simulation.generator import EventInjection, SimulationConfig, SyntheticTelemetryGenerator
from simulation.network_model import MarkovConnectivityModel

RARE_EVENT_SCHEMA = {
    "schema_version": "1.0",
    "row_type": "rare_event_telemetry",
    "target": "CriticalityScenario.value",
    "features": [
        "temperature",
        "humidity",
        "rainfall",
        "soil_moisture",
        "ph",
        "nitrogen",
        "phosphorus",
        "potassium",
        "salinity",
        "leaf_wetness",
        "pest_pressure",
        "tank_level",
        "irrigation_flow",
        "equipment_health",
        "tinyml_confidence",
        "link_state",
        "actuator_valve_open",
        "actuator_pump_active",
    ],
    "labels": [scenario.value for scenario in CriticalityScenario],
    "caveat": "Synthetic rows support ML plumbing and rare-event coverage; they are not real farm accuracy evidence.",
}


def generate_rare_event_dataset(seed: int = 11, repeats_per_scenario: int = 4) -> list[dict[str, Any]]:
    if repeats_per_scenario < 1:
        raise ValueError("repeats_per_scenario must be positive")
    scenarios = [scenario for scenario in CriticalityScenario if scenario is not CriticalityScenario.NORMAL]
    steps = len(scenarios) * repeats_per_scenario
    config = SimulationConfig(
        zone_count=1,
        sensors_per_zone=1,
        duration_minutes=steps * 10,
        sample_interval_minutes=10,
        seed=seed,
    )
    events = [
        EventInjection("zone-1", scenario, index * repeats_per_scenario, repeats_per_scenario)
        for index, scenario in enumerate(scenarios)
    ]
    records = SyntheticTelemetryGenerator(
        config,
        events=events,
        connectivity=MarkovConnectivityModel(seed=seed),
    ).generate()
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "schema_version": RARE_EVENT_SCHEMA["schema_version"],
                "event_id": record.event_id,
                "device_id": record.device_id,
                "zone_id": record.zone_id,
                "timestamp": record.timestamp.isoformat(),
                "features": {
                    **record.readings,
                    "tinyml_confidence": record.tinyml_confidence,
                    "tinyml_class": record.tinyml_class,
                    "link_state": record.link_state.value,
                    "actuator_valve_open": record.actuator_state.get("valve_open", False),
                    "actuator_pump_active": record.actuator_state.get("pump_active", False),
                },
                "target": record.event_label.value,
                "sensor_fault_label": record.sensor_fault_label.value,
                "delivered": record.delivered,
                "source": "digital_twin_seeded_rare_event_generator",
            }
        )
    return rows


def write_rare_event_dataset(output_dir: Path, seed: int = 11, repeats_per_scenario: int = 4) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = generate_rare_event_dataset(seed=seed, repeats_per_scenario=repeats_per_scenario)
    (output_dir / "rare_events.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = {
        "schema": RARE_EVENT_SCHEMA,
        "seed": seed,
        "repeats_per_scenario": repeats_per_scenario,
        "records": len(rows),
        "file": "rare_events.jsonl",
    }
    (output_dir / "rare_events_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
