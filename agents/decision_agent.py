from __future__ import annotations

from llm_factory import safe_invoke

DECISION_PROMPT = """
You are the final decision agent in a smart farm fog layer pipeline.
You receive a complete picture of trust scores, sanity checks, and criticality assessment.
Your job is to make the final action decision.

Trust levels:
- 0.8-1.0: HIGH - Act Locally
- 0.5-0.8: MEDIUM - Ask Human / Validation Agent
- 0.0-0.5: LOW - Send to Cloud

Respond ONLY with this JSON, nothing else:
{
    "reasoning": "one sentence explanation",
    "decision": "act_locally or validate or escalate",
    "action_required": "irrigate or stop_irrigation or adjust_flow or trigger_alert or no_action or cloud or validation"
}
"""

DECISION_FALLBACK: dict = {
    "reasoning": "LLM unavailable - escalating to cloud for safety",
    "decision": "escalate",
    "action_required": "cloud",
}


class DecisionAgent:
    """Final action decision agent (no local state)."""

    def run(self, pipeline_context: dict) -> dict:
        user_message = f"""
Complete pipeline context:

Sensor ID: {pipeline_context.get('sensor_id')}
Trust Score: {pipeline_context.get('trust_score')}
Trust Level: {pipeline_context.get('trust_level')}
Sanity Score: {pipeline_context.get('sanity_score')}
Failed Fields: {pipeline_context.get('failed_fields', [])}
Critical: {pipeline_context.get('critical')}
Scenario: {pipeline_context.get('scenario')}
Severity: {pipeline_context.get('severity')}
TinyML Recommendation: {pipeline_context.get('tinyml_recommendation')}

Make the final farm action decision.
Respond ONLY with JSON.
"""
        return safe_invoke(DECISION_PROMPT, user_message, DECISION_FALLBACK)
