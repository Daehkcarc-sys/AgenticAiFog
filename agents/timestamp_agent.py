from __future__ import annotations

from datetime import datetime, timezone

from config import FRESHNESS_LIMIT_SECONDS
from models import TimestampResult


class TimestampAgent:
    """Trust Layer — lightweight freshness assessment for Fog nodes.

    Performs a rapid timestamp check (not a full cryptographic replay
    detection) suitable for resource-constrained Fog hardware such as
    an Industrial PC, NVIDIA Jetson, or server-class gateway.  Scores
    decay from 1.0 (<60s) to 0.0 (>=600s).
    """

    def __init__(self, freshness_limit_seconds: int = FRESHNESS_LIMIT_SECONDS):
        self.freshness_limit = freshness_limit_seconds

    def run(self, sensor_data: dict) -> TimestampResult:
        timestamp = sensor_data.get("timestamp", "")

        try:
            reading_time = datetime.fromisoformat(timestamp).replace(
                tzinfo=timezone.utc
            )
            age_seconds = (datetime.now(timezone.utc) - reading_time).total_seconds()

            if age_seconds < 60:
                score = 1.0
            elif age_seconds < 180:
                score = 0.8
            elif age_seconds < self.freshness_limit:
                score = 0.6
            elif age_seconds < 600:
                score = 0.3
            else:
                return TimestampResult(
                    passed=False,
                    freshness_score=0.0,
                    reason=f"Timestamp too old ({age_seconds:.0f}s) - possible replay attack",
                )

            return TimestampResult(
                passed=True,
                freshness_score=score,
                age_seconds=age_seconds,
                reason="Timestamp valid",
            )

        except ValueError:
            return TimestampResult(
                passed=False,
                freshness_score=0.0,
                reason="Malformed timestamp - suspicious",
            )
