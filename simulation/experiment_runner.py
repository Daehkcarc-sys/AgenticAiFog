"""Command-line entry point for reproducible B0/B2 simulations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from models import CriticalityScenario
from simulation.baselines import Baseline, BaselineSimulator
from simulation.experiment_metrics import summarize_outcomes
from simulation.generator import (
    EventInjection,
    FaultInjection,
    SimulationConfig,
    SyntheticTelemetryGenerator,
)
from simulation.network_model import MarkovConnectivityModel
from simulation.telemetry_schema import SensorFault


def default_injections(
    config: SimulationConfig,
) -> tuple[list[EventInjection], list[FaultInjection]]:
    event_duration = max(1, min(3, config.steps // 3))
    first_start = 0 if config.steps <= event_duration else 1
    second_start = min(config.steps - event_duration, max(event_duration + 1, config.steps // 2))
    events = [
        EventInjection(
            "zone-1", CriticalityScenario.WATER_DEFICIT, first_start, event_duration
        )
    ]
    if config.zone_count > 1 and second_start >= 0:
        events.append(
            EventInjection(
                "zone-2", CriticalityScenario.HEAT_STRESS, second_start, event_duration
            )
        )
    faults = [
        FaultInjection(
            "zone-1-sensor-1",
            SensorFault.GRADUAL_DRIFT,
            max(0, config.steps - event_duration),
            event_duration,
            "temperature",
            1.5,
        )
    ]
    if config.sensors_per_zone > 1:
        faults.append(
            FaultInjection(
                "zone-1-sensor-2",
                SensorFault.BURST_LOSS,
                second_start,
                event_duration,
            )
        )
    return events, faults


def run_experiment(
    baseline: Baseline,
    seed: int = 5,
    duration_minutes: int = 120,
    sample_interval_minutes: int = 10,
) -> dict[str, Any]:
    config = SimulationConfig(
        seed=seed,
        duration_minutes=duration_minutes,
        sample_interval_minutes=sample_interval_minutes,
    )
    events, faults = default_injections(config)
    records = SyntheticTelemetryGenerator(
        config,
        events,
        faults,
        MarkovConnectivityModel(seed=seed),
    ).generate()
    summary = summarize_outcomes(BaselineSimulator(baseline).run(records))
    summary["seed"] = seed
    summary["simulation_steps"] = config.steps
    summary["zones"] = config.zone_count
    summary["sensors_per_zone"] = config.sensors_per_zone
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", choices=["B0", "B2", "all"], default="all")
    parser.add_argument(
        "--seed",
        type=int,
        default=5,
        help="Seed 5 exercises terrestrial, NTN, and offline states in the default run",
    )
    parser.add_argument("--duration-minutes", type=int, default=120)
    parser.add_argument("--sample-interval-minutes", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    baselines = (
        list(Baseline)
        if args.baseline == "all"
        else [Baseline(args.baseline)]
    )
    result = {
        baseline.value: run_experiment(
            baseline,
            args.seed,
            args.duration_minutes,
            args.sample_interval_minutes,
        )
        for baseline in baselines
    }
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
