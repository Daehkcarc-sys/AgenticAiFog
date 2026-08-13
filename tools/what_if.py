"""CLI for what-if scenario analysis using the digital twin engine.

Runs a forward simulation from the current (or loaded) twin state and reports
projected risk, soil moisture, and crop risks after N 30-minute steps.

Usage examples::

    # Simulate an irrigation drought scenario on zone-1 for 3 steps
    python -m tools.what_if --zone zone-1 --scenario irrigation --horizon 3

    # Check what happens with a disease risk scenario on zone-2
    python -m tools.what_if --zone zone-2 --scenario disease_risk

    # Load saved twin state and run what-if
    python -m tools.what_if --zone zone-1 --scenario heat_stress \\
        --state state/digital_twin.db

    # List available scenarios and interventions
    python -m tools.what_if --list-scenarios

Available scenarios
-------------------
  irrigation        — drought / low-moisture scenario; default intervention: irrigate
  disease_risk      — high humidity and leaf wetness; default: reduce_humidity
  heat_stress       — extreme temperature; default: cooling_irrigation
  equipment_failure — degraded equipment health; default: dispatch_maintenance
  resource_allocation — multi-zone resource pressure; default: prioritize_high_risk_zones
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCENARIOS = {
    "irrigation": "irrigate",
    "disease_risk": "reduce_humidity",
    "heat_stress": "cooling_irrigation",
    "equipment_failure": "dispatch_maintenance",
    "resource_allocation": "prioritize_high_risk_zones",
}


def _load_twin_from_db(db_path: Path):
    """Load the latest twin state from a SQLite state database.

    Falls back to a fresh engine if the database or state table is missing.
    """
    from digital_twin.simulator import DigitalTwinEngine

    twin = DigitalTwinEngine()
    if not db_path.exists():
        return twin

    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT payload FROM twin_state ORDER BY created_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            state = json.loads(row[0])
            # Hydrate zones from dashboard snapshot
            for zone_state in state.get("zones", []):
                zone_id = zone_state.get("zone_id", "unknown")
                zone = twin.farm.zone(zone_id)
                soil = zone_state.get("soil", {})
                for field in ("moisture", "ph", "nitrogen", "phosphorus", "potassium", "salinity"):
                    val = soil.get(field)
                    if val is not None:
                        setattr(zone.soil, field, float(val))
                crop = zone_state.get("crop", {})
                for cfield in ("disease_risk", "heat_stress_risk", "pest_risk"):
                    val = crop.get(cfield)
                    if val is not None:
                        setattr(zone.crop, cfield, float(val))
                zone.risk_index = float(zone_state.get("risk_index", 0.0))
                zone.last_scenario = zone_state.get("last_scenario")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not load twin state from {db_path}: {exc}", file=sys.stderr)

    return twin


def run_what_if(
    zone_id: str,
    scenario: str,
    intervention: str | None = None,
    horizon: int = 3,
    state_db: Path | None = None,
) -> dict:
    twin = _load_twin_from_db(state_db) if state_db else _fresh_twin()
    result = twin.what_if(
        zone_id=zone_id,
        scenario=scenario,
        intervention=intervention,
        horizon_steps=horizon,
    )
    return {
        "zone_id": result.zone_id,
        "scenario": result.scenario,
        "baseline_risk": result.baseline_risk,
        "projected_risk": result.projected_risk,
        "risk_delta": result.delta,
        "recommendation": result.recommendation,
        "horizon_steps": horizon,
        "minutes_per_step": 30,
        "projected_state": result.projected_state,
        "trace": result.trace,
        "assumptions": result.assumptions,
    }


def _fresh_twin():
    from digital_twin.simulator import DigitalTwinEngine
    twin = DigitalTwinEngine()
    # Seed with representative initial zone state
    for zone_id in ("zone-1", "zone-2"):
        zone = twin.farm.zone(zone_id)
        zone.soil.moisture = 45.0
        zone.soil.ph = 6.5
        zone.soil.salinity = 1.2
    return twin


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--zone", default="zone-1", help="Zone ID to analyse")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS),
        default="irrigation",
        help="Scenario to simulate",
    )
    parser.add_argument(
        "--intervention",
        default=None,
        help="Override the default intervention action",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=3,
        help="Number of 30-minute forward steps (default: 3)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        metavar="DB_PATH",
        help="Path to digital_twin.db to load current state (optional)",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="Print available scenarios and exit",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Save JSON result to this file",
    )
    args = parser.parse_args()

    if args.list_scenarios:
        print("Available scenarios and their default interventions:")
        for scenario, default_iv in SCENARIOS.items():
            print(f"  {scenario:<25} -> {default_iv}")
        sys.exit(0)

    result = run_what_if(
        zone_id=args.zone,
        scenario=args.scenario,
        intervention=args.intervention,
        horizon=args.horizon,
        state_db=args.state,
    )

    rendered = json.dumps(result, indent=2)
    print(rendered)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"\nSaved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
