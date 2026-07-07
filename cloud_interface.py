# cloud_interface.py
# Simulates cloud layer responses when fog escalates
# In production this would use Apache Kafka (see architecture diagram)
# Topics: sensor-data, critical-events, trust-events, fog-decisions

from __future__ import annotations

import json

from llm_factory import safe_invoke

CLOUD_PROMPT = """
You are a cloud intelligence agent in a smart farm global platform.
You receive escalated decisions from fog layer agents that couldn't act locally.
You have access to global context, historical data, and advanced ML models.

You must make a final decision with full authority.
Be specific about what action to take and why.

Respond ONLY with this JSON:
{
    "cloud_decision": "action to take",
    "reasoning": "one sentence with global context",
    "send_back_to_fog": true or false,
    "updated_policy": "any policy update to send back to fog"
}
"""

CLOUD_FALLBACK: dict = {
    "cloud_decision": "manual_review",
    "reasoning": "Cloud LLM unavailable - flagging for human review",
    "send_back_to_fog": False,
    "updated_policy": None,
}


class CloudInterface:
    """Simulated cloud layer with LLM-powered global decision making."""

    def escalate(self, context: dict) -> dict:
        print("[KAFKA] Publishing to 'fog-decisions' topic")
        print("[CLOUD] Global platform processing...")

        user_message = f"""
Escalated decision from fog layer:

Sensor: {context.get('sensor_id')}
Trust Score: {context.get('trust_score')}
Scenario: {context.get('scenario')}
Critical: {context.get('critical')}
Original Decision: {json.dumps(context.get('decision', {}), indent=2)}
Raw Readings: {json.dumps(context.get('raw_readings', {}), indent=2)}

Make a final cloud-level decision.
Respond ONLY with JSON.
"""
        return safe_invoke(CLOUD_PROMPT, user_message, CLOUD_FALLBACK)

    def notify_rejection(self, sensor_id: str, reason: str) -> None:
        print(f"[KAFKA] Publishing rejection event to 'trust-events' topic")
        print(f"[CLOUD] Logging rejection for sensor {sensor_id}: {reason}")
