"""Command-line entry point for reproducible B0–B5 simulations.

Usage examples:
    python -m simulation.experiment_runner --baseline all --seed 5
    python -m simulation.experiment_runner --baseline B5 --seeds 5 10 15
    python -m simulation.experiment_runner --baseline all --seeds 1 2 3 4 5 --output results.json
"""

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


def run_multi_seed(
    baselines: list[Baseline],
    seeds: list[int],
    duration_minutes: int = 120,
    sample_interval_minutes: int = 10,
) -> dict[str, Any]:
    """Run each baseline over multiple seeds; return per-baseline aggregates."""
    results: dict[str, list[dict[str, Any]]] = {b.value: [] for b in baselines}
    for seed in seeds:
        for baseline in baselines:
            summary = run_experiment(baseline, seed, duration_minutes, sample_interval_minutes)
            results[baseline.value].append(summary)

    aggregated: dict[str, Any] = {}
    for bname, runs in results.items():
        if not runs:
            continue
        metrics_to_agg = ["decision_coverage", "mean_latency_ms", "bytes_to_cloud",
                          "communication_cost", "energy_units", "macro_f1_observed_abnormal",
                          "false_alarm_rate"]
        agg: dict[str, Any] = {"seeds": seeds, "n_runs": len(runs), "per_seed": runs}
        for metric in metrics_to_agg:
            values = [r[metric] for r in runs if r.get(metric) is not None]
            if values:
                mean = sum(values) / len(values)
                variance = sum((v - mean) ** 2 for v in values) / len(values)
                agg[f"{metric}_mean"] = round(mean, 4)
                agg[f"{metric}_std"] = round(variance ** 0.5, 4)
        aggregated[bname] = agg
    return aggregated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        choices=["B0", "B1", "B2", "B3", "B4", "B5", "all"],
        default="all",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=5,
        help="Single seed (ignored when --seeds is used)",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=None,
        help="Multiple seeds for multi-seed runs (e.g. 1 2 3 4 5)",
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

    if args.seeds and len(args.seeds) > 1:
        result = run_multi_seed(
            baselines,
            args.seeds,
            args.duration_minutes,
            args.sample_interval_minutes,
        )
    else:
        seeds = args.seeds or [args.seed]
        result = {
            baseline.value: run_experiment(
                baseline,
                seeds[0],
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
