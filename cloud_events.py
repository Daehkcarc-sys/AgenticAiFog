"""Cloud/Kafka event contracts for fog-to-cloud synchronization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

TOPICS = {
    "sensor_data": "sensor-data",
    "trust_events": "trust-events",
    "fog_decisions": "fog-decisions",
    "critical_events": "critical-events",
    "model_updates": "model-updates",
    "policy_updates": "policy-updates",
    "dead_letter": "fog-dead-letter",
    "twin_state": "twin-state",
    "twin_sync": "twin-sync",
    "twin_command": "twin-command",
}

SCHEMA_VERSIONS = {
    "fog_summary": "1.0",
    "trust_event": "1.0",
    "fog_decision": "1.0",
    "critical_event": "1.0",
    "model_update": "1.0",
    "policy_update": "1.0",
    "dead_letter": "1.0",
    "twin_state": "1.0",
    "twin_sync": "1.0",
    "twin_command": "1.0",
}


@dataclass(frozen=True)
class CloudEvent:
    """Standard event envelope for HTTP/Kafka/local queue publishers."""

    event_type: str
    payload: dict[str, Any]
    source: str = "fog-node"
    schema_version: str = "1.0"
    event_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def envelope(event_type: str, payload: dict[str, Any], source: str = "fog-node") -> dict[str, Any]:
    """Create a versioned cloud event envelope."""
    return CloudEvent(
        event_type=event_type,
        payload=payload,
        source=source,
        schema_version=SCHEMA_VERSIONS.get(event_type, "1.0"),
    ).to_dict()


def topic_for_event(event_type: str, payload: dict[str, Any] | None = None) -> str:
    """Resolve a cloud event type to its Kafka/local queue topic."""
    payload = payload or {}
    if event_type == "fog_summary":
        if payload.get("critical") or payload.get("severity") == "high":
            return TOPICS["critical_events"]
        return TOPICS["sensor_data"]
    if event_type == "trust_event":
        return TOPICS["trust_events"]
    if event_type == "fog_decision":
        return TOPICS["fog_decisions"]
    if event_type == "critical_event":
        return TOPICS["critical_events"]
    if event_type == "model_update":
        return TOPICS["model_updates"]
    if event_type == "policy_update":
        return TOPICS["policy_updates"]
    if event_type == "dead_letter":
        return TOPICS["dead_letter"]
    if event_type == "twin_state":
        return TOPICS["twin_state"]
    if event_type == "twin_sync":
        return TOPICS["twin_sync"]
    if event_type == "twin_command":
        return TOPICS["twin_command"]
    return TOPICS["sensor_data"]


def validate_event(event: dict[str, Any]) -> None:
    """Small schema guard for local tests and publisher boundaries."""
    required = {"event_id", "event_type", "schema_version", "source", "created_at", "payload"}
    missing = required - set(event)
    if missing:
        raise ValueError(f"cloud event missing required fields: {sorted(missing)}")
    if not isinstance(event["payload"], dict):
        raise ValueError("cloud event payload must be a dict")



