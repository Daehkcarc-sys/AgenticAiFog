"""Dependency-free metrics for baseline experiment outcomes."""

from __future__ import annotations

from statistics import mean, median
from typing import Any

from models import CriticalityScenario
from simulation.baselines import DecisionOutcome
from simulation.telemetry_schema import LinkState


def _class_metrics(
    outcomes: list[DecisionOutcome], scenario: CriticalityScenario
) -> dict[str, float | int]:
    decided = [outcome for outcome in outcomes if outcome.decision_made]
    true_positive = sum(
        outcome.true_event is scenario and outcome.predicted_event is scenario
        for outcome in decided
    )
    false_positive = sum(
        outcome.true_event is not scenario and outcome.predicted_event is scenario
        for outcome in decided
    )
    false_negative = sum(
        outcome.true_event is scenario and outcome.predicted_event is not scenario
        for outcome in decided
    )
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "support": sum(outcome.true_event is scenario for outcome in decided),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def summarize_outcomes(outcomes: list[DecisionOutcome]) -> dict[str, Any]:
    total = len(outcomes)
    decided = [outcome for outcome in outcomes if outcome.decision_made]
    latencies = [
        outcome.latency_ms
        for outcome in decided
        if outcome.latency_ms is not None
    ]
    per_class = {
        scenario.value: _class_metrics(outcomes, scenario)
        for scenario in CriticalityScenario
    }
    observed_abnormal_f1 = [
        metrics["f1"]
        for name, metrics in per_class.items()
        if name != CriticalityScenario.NORMAL.value and metrics["support"] > 0
    ]
    normal_decisions = [
        outcome for outcome in decided if outcome.true_event is CriticalityScenario.NORMAL
    ]
    false_alarms = sum(
        outcome.predicted_event is not CriticalityScenario.NORMAL
        for outcome in normal_decisions
    )
    return {
        "baseline": outcomes[0].baseline.value if outcomes else None,
        "total_records": total,
        "decisions": len(decided),
        "decision_coverage": round(len(decided) / total, 4) if total else 0.0,
        "mean_latency_ms": round(mean(latencies), 3) if latencies else None,
        "median_latency_ms": round(median(latencies), 3) if latencies else None,
        "bytes_to_cloud": sum(outcome.bytes_to_cloud for outcome in outcomes),
        "bytes_by_link": {
            state.value: sum(
                outcome.bytes_to_cloud
                for outcome in outcomes
                if outcome.link_state is state
            )
            for state in LinkState
        },
        "communication_cost": round(
            sum(outcome.communication_cost for outcome in outcomes), 6
        ),
        "energy_units": round(sum(outcome.energy_units for outcome in outcomes), 3),
        "macro_f1_observed_abnormal": round(mean(observed_abnormal_f1), 4)
        if observed_abnormal_f1
        else 0.0,
        "false_alarm_rate": round(false_alarms / len(normal_decisions), 4)
        if normal_decisions
        else 0.0,
        "per_class": per_class,
    }
