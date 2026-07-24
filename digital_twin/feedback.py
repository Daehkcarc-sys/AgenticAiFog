"""Human feedback and policy/model update path definitions for the twin."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

FEEDBACK_EVENT_SCHEMA = {
    "schema_version": "1.0",
    "event_type": "human_feedback",
    "required_fields": ["event_id", "zone_id", "reviewer_id", "label", "created_at"],
    "optional_fields": ["sensor_id", "scenario", "corrected_action", "notes", "confidence"],
    "usage": "Dashboard feedback becomes labeled data for Sonic/Sarra after review/export.",
}

POLICY_UPDATE_SCHEMA = {
    "schema_version": "1.0",
    "event_type": "policy_update",
    "topic": "policy-updates",
    "required_fields": ["policy_id", "version", "rules", "created_at"],
    "path": "cloud PAP/dashboard -> Kafka policy-updates -> fog LocalRuleStore.update(...) -> PEP gates",
}

MODEL_UPDATE_SCHEMA = {
    "schema_version": "1.0",
    "event_type": "model_update",
    "topic": "model-updates",
    "required_fields": ["version", "source_path or source_url", "checksum_sha256", "created_at"],
    "path": "cloud model registry -> Kafka model-updates -> ModelUpdateStore.install_update(...) -> fog reload hook",
}


@dataclass(frozen=True, slots=True)
class HumanFeedback:
    event_id: str
    zone_id: str
    reviewer_id: str
    label: str
    sensor_id: str | None = None
    scenario: str | None = None
    corrected_action: str | None = None
    notes: str | None = None
    confidence: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_training_label(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source": "dashboard_human_feedback",
            "event_id": self.event_id,
            "zone_id": self.zone_id,
            "sensor_id": self.sensor_id,
            "target": self.label,
            "scenario": self.scenario,
            "corrected_action": self.corrected_action,
            "reviewer_id": self.reviewer_id,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_at": self.created_at,
        }
