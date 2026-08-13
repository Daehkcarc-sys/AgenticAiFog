"""Long-term sensor reliability history and fault-pattern detection (items 13–14).

Maintains a rolling window of trust scores per sensor and detects the four
injected fault patterns (gradual drift, random dropout, stuck-at, burst loss)
from the trust trajectory alone — without access to the ground-truth fault
label.  This is the evaluation counterpart to the ground-truth-based trust
simulator in simulation/baselines.py.

Usage::

    history = SensorTrustHistory()
    for record, trust in zip(records, trust_scores):
        result = history.update(record.device_id, trust, record)
        if result.fault_detected:
            print(f"{record.device_id}: {result.fault_pattern} detected")
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TrustHistoryEntry:
    trust_score: float
    reading: dict[str, Any]
    sequence_number: int


@dataclass(frozen=True)
class FaultDetectionResult:
    sensor_id: str
    trust_score: float
    running_mean: float
    fault_detected: bool
    fault_pattern: str | None
    evidence: str


class SensorTrustHistory:
    """Tracks rolling trust scores per sensor and detects fault patterns.

    Detection rules (no ground-truth labels needed):

    GRADUAL_DRIFT   — mean trust trending downward over the window;
                      detected when linear slope < -0.05 per reading.
    RANDOM_DROPOUT  — high variance in trust scores; detected when
                      stdev > 0.20 over the last N readings.
    STUCK_AT        — extremely low variance in raw readings for a field;
                      detected when inter-reading range < 0.01 for a key field.
    BURST_LOSS      — a sudden cluster of missing/undelivered records;
                      detected when consecutive_missed >= 3.
    """

    def __init__(self, window: int = 20) -> None:
        if window < 3:
            raise ValueError("window must be at least 3")
        self._window = window
        self._trust: defaultdict[str, deque[TrustHistoryEntry]] = defaultdict(
            lambda: deque(maxlen=self._window)
        )
        self._missed: defaultdict[str, int] = defaultdict(int)

    def update(
        self,
        sensor_id: str,
        trust_score: float,
        record: Any,
    ) -> FaultDetectionResult:
        """Record a new trust score and return a fault detection result."""
        delivered = getattr(record, "delivered", True)
        if not delivered:
            self._missed[sensor_id] += 1
            if self._missed[sensor_id] >= 3:
                return FaultDetectionResult(
                    sensor_id=sensor_id,
                    trust_score=trust_score,
                    running_mean=trust_score,
                    fault_detected=True,
                    fault_pattern="burst_loss",
                    evidence=(
                        f"{self._missed[sensor_id]} consecutive undelivered records"
                    ),
                )
            return FaultDetectionResult(
                sensor_id=sensor_id,
                trust_score=trust_score,
                running_mean=trust_score,
                fault_detected=False,
                fault_pattern=None,
                evidence="undelivered record",
            )
        else:
            self._missed[sensor_id] = 0

        readings = getattr(record, "readings", {})
        seq = getattr(record, "sequence_number", 0)
        entry = TrustHistoryEntry(
            trust_score=trust_score,
            reading={k: v for k, v in readings.items() if isinstance(v, (int, float))},
            sequence_number=seq,
        )
        self._trust[sensor_id].append(entry)

        window = list(self._trust[sensor_id])
        scores = [e.trust_score for e in window]
        running_mean = statistics.mean(scores)

        if len(scores) < 3:
            return FaultDetectionResult(
                sensor_id=sensor_id,
                trust_score=trust_score,
                running_mean=running_mean,
                fault_detected=False,
                fault_pattern=None,
                evidence="insufficient history",
            )

        # ── Gradual drift: monotonically decreasing trust ─────────────────
        slope = self._linear_slope(scores)
        if slope < -0.05:
            return FaultDetectionResult(
                sensor_id=sensor_id,
                trust_score=trust_score,
                running_mean=running_mean,
                fault_detected=True,
                fault_pattern="gradual_drift",
                evidence=f"trust slope={slope:.3f}/reading over last {len(scores)}",
            )

        # ── Random dropout: high trust variance ───────────────────────────
        stdev = statistics.stdev(scores)
        if stdev > 0.20:
            return FaultDetectionResult(
                sensor_id=sensor_id,
                trust_score=trust_score,
                running_mean=running_mean,
                fault_detected=True,
                fault_pattern="random_dropout",
                evidence=f"trust stdev={stdev:.3f} over last {len(scores)}",
            )

        # ── Stuck-at: near-zero variance in a key reading field ───────────
        key_fields = ["soil_moisture", "temperature", "humidity"]
        for field in key_fields:
            values = [
                e.reading[field]
                for e in window
                if field in e.reading
            ]
            if len(values) >= 3:
                field_range = max(values) - min(values)
                if field_range < 0.01:
                    return FaultDetectionResult(
                        sensor_id=sensor_id,
                        trust_score=trust_score,
                        running_mean=running_mean,
                        fault_detected=True,
                        fault_pattern="stuck_at",
                        evidence=(
                            f"{field} range={field_range:.4f} over {len(values)} readings"
                        ),
                    )

        return FaultDetectionResult(
            sensor_id=sensor_id,
            trust_score=trust_score,
            running_mean=running_mean,
            fault_detected=False,
            fault_pattern=None,
            evidence="no fault pattern detected",
        )

    def history(self, sensor_id: str) -> list[float]:
        """Return trust score history for a sensor."""
        return [e.trust_score for e in self._trust.get(sensor_id, [])]

    @staticmethod
    def _linear_slope(values: list[float]) -> float:
        """OLS slope of values treated as equally spaced time series."""
        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        denom = sum((i - x_mean) ** 2 for i in range(n))
        if denom == 0:
            return 0.0
        numer = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        return numer / denom
