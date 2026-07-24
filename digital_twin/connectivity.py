"""Inter-twin and intra-twin connectivity contracts."""

from __future__ import annotations

from typing import Any

from cloud_events import envelope

TWIN_CONNECTIVITY_TOPICS = {
    "twin_state": "twin-state",
    "twin_sync": "twin-sync",
    "twin_command": "twin-command",
}


def twin_state_event(farm_id: str, twin_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return envelope(
        "twin_state",
        {"farm_id": farm_id, "twin_id": twin_id, "state": state},
        source="digital-twin-service",
    )


def twin_sync_event(source_twin: str, target_twin: str, summary: dict[str, Any]) -> dict[str, Any]:
    return envelope(
        "twin_sync",
        {"source_twin": source_twin, "target_twin": target_twin, "summary": summary},
        source="digital-twin-service",
    )


def twin_command_event(target_twin: str, command: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return envelope(
        "twin_command",
        {"target_twin": target_twin, "command": command, "parameters": parameters or {}},
        source="digital-twin-service",
    )


def validate_twin_connectivity_event(event: dict[str, Any]) -> None:
    event_type = event.get("event_type")
    payload = event.get("payload", {})
    if event_type == "twin_state":
        required = {"farm_id", "twin_id", "state"}
    elif event_type == "twin_sync":
        required = {"source_twin", "target_twin", "summary"}
    elif event_type == "twin_command":
        required = {"target_twin", "command", "parameters"}
    else:
        raise ValueError(f"unsupported twin connectivity event: {event_type}")
    missing = required - set(payload)
    if missing:
        raise ValueError(f"twin connectivity event missing fields: {sorted(missing)}")
