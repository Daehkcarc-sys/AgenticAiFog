"""Kafka/API contract for fog summaries consumed by the digital twin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REQUIRED_FOG_SUMMARY_FIELDS = {"sensor_id"}
OPTIONAL_FOG_SUMMARY_FIELDS = {
    "zone_id",
    "zone",
    "scenario",
    "severity",
    "critical",
    "decision",
    "decision_source",
    "confidence",
    "result",
    "trust_score",
    "raw_readings",
    "context_summary",
    "multimodal_summary",
    "explanation_trace",
    "policy_version",
}


@dataclass(frozen=True, slots=True)
class FogSummaryContract:
    """Normalized payload consumed from the `fog_summary` cloud event."""

    sensor_id: str
    zone_id: str
    scenario: str | None = None
    severity: str | None = None
    critical: bool = False
    decision: str | None = None
    decision_source: str | None = None
    confidence: float | None = None
    result: str | None = None
    trust_score: float | None = None
    raw_readings: dict[str, Any] | None = None
    context_summary: str | None = None
    multimodal_summary: str | None = None
    explanation_trace: dict[str, Any] | None = None
    policy_version: str | int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "FogSummaryContract":
        validate_fog_summary_payload(payload)
        zone_id = str(payload.get("zone_id") or payload.get("zone") or "default-zone")
        return cls(
            sensor_id=str(payload["sensor_id"]),
            zone_id=zone_id,
            scenario=_optional_str(payload.get("scenario")),
            severity=_optional_str(payload.get("severity")),
            critical=bool(payload.get("critical", False)),
            decision=_optional_str(payload.get("decision")),
            decision_source=_optional_str(payload.get("decision_source")),
            confidence=_optional_float(payload.get("confidence")),
            result=_optional_str(payload.get("result")),
            trust_score=_optional_float(payload.get("trust_score")),
            raw_readings=payload.get("raw_readings") if isinstance(payload.get("raw_readings"), dict) else None,
            context_summary=_optional_str(payload.get("context_summary")),
            multimodal_summary=_optional_str(payload.get("multimodal_summary")),
            explanation_trace=payload.get("explanation_trace") if isinstance(payload.get("explanation_trace"), dict) else None,
            policy_version=payload.get("policy_version"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "zone_id": self.zone_id,
            "scenario": self.scenario,
            "severity": self.severity,
            "critical": self.critical,
            "decision": self.decision,
            "decision_source": self.decision_source,
            "confidence": self.confidence,
            "result": self.result,
            "trust_score": self.trust_score,
            "raw_readings": self.raw_readings or {},
            "context_summary": self.context_summary,
            "multimodal_summary": self.multimodal_summary,
            "explanation_trace": self.explanation_trace or {},
            "policy_version": self.policy_version,
        }


def validate_fog_summary_payload(payload: dict[str, Any]) -> None:
    missing = REQUIRED_FOG_SUMMARY_FIELDS - set(payload)
    if missing:
        raise ValueError(f"fog summary missing required fields: {sorted(missing)}")
    if not isinstance(payload.get("sensor_id"), str) or not payload["sensor_id"]:
        raise ValueError("fog summary sensor_id must be a non-empty string")
    raw_readings = payload.get("raw_readings")
    if raw_readings is not None and not isinstance(raw_readings, dict):
        raise ValueError("fog summary raw_readings must be a dict when provided")
    confidence = payload.get("confidence")
    if confidence is not None and not isinstance(confidence, (int, float)):
        raise ValueError("fog summary confidence must be numeric when provided")
    trust_score = payload.get("trust_score")
    if trust_score is not None and not isinstance(trust_score, (int, float)):
        raise ValueError("fog summary trust_score must be numeric when provided")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if value is None or not isinstance(value, (int, float)):
        return None
    return float(value)
