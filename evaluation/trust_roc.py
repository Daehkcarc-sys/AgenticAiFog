"""Trust score ROC-AUC against sensor fault ground truth (item 15).

Usage::

    from evaluation.trust_roc import compute_roc_auc, roc_curve, TrustSample
    from simulation.baselines import _simulated_trust

    samples = [
        TrustSample(
            trust_score=_simulated_trust(record),
            is_faulty=record.sensor_fault_label.value != "none",
        )
        for record in records
        if record.delivered
    ]
    auc = compute_roc_auc(samples)
    print(f"Trust ROC-AUC: {auc:.4f}")

A higher AUC means trust scores are better at separating faulty from healthy
readings.  An AUC of 0.5 is random; 1.0 is perfect separation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TrustSample:
    """One reading's trust score paired with its ground-truth fault label."""
    trust_score: float
    is_faulty: bool


def roc_curve(
    samples: Sequence[TrustSample],
) -> list[tuple[float, float]]:
    """Compute (FPR, TPR) pairs for all unique trust thresholds.

    We treat a *low trust score* as a positive prediction of a fault.
    Thresholds sweep from high to low, so lowering the threshold increases
    both sensitivity and false-alarm rate.
    """
    if not samples:
        return [(0.0, 0.0), (1.0, 1.0)]

    n_pos = sum(1 for s in samples if s.is_faulty)
    n_neg = len(samples) - n_pos

    if n_pos == 0 or n_neg == 0:
        return [(0.0, 0.0), (1.0, 1.0)]

    sorted_samples = sorted(samples, key=lambda s: s.trust_score, reverse=True)

    points: list[tuple[float, float]] = [(0.0, 0.0)]
    tp = fp = 0
    for sample in sorted_samples:
        if sample.is_faulty:
            tp += 1
        else:
            fp += 1
        points.append((fp / n_neg, tp / n_pos))

    return points


def compute_roc_auc(samples: Sequence[TrustSample]) -> float:
    """Compute AUC using the trapezoidal rule on the ROC curve."""
    points = roc_curve(samples)
    auc = 0.0
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        auc += (x1 - x0) * (y0 + y1) / 2.0
    return round(auc, 4)


def samples_from_records(records) -> list[TrustSample]:
    """Build TrustSample list from TelemetryRecord objects using simulated trust."""
    from simulation.baselines import _simulated_trust
    from simulation.telemetry_schema import SensorFault

    return [
        TrustSample(
            trust_score=_simulated_trust(record),
            is_faulty=record.sensor_fault_label is not SensorFault.NONE,
        )
        for record in records
        if record.delivered
    ]
