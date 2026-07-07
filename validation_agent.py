from __future__ import annotations

import json

from llm_factory import safe_invoke

VALIDATION_PROMPT = """
You are a validation agent in a smart farm fog layer pipeline.
Your job is to give a second opinion on decisions made by the main fog agent.
You are called only when trust is MEDIUM (0.5-0.8) - not high enough to act alone.

You must be conservative - when in doubt, escalate to cloud.
A wrong irrigation decision can damage crops.

Consider:
- Does the recommended action make sense given the sensor readings?
- Is the criticality scenario consistent with the data?
- Is the trust score high enough for this specific action?

Respond ONLY with this JSON, nothing else:
{
    "verdict": "confirmed or escalate",
    "confidence": 0.0 to 1.0,
    "reasoning": "one sentence explanation"
}
"""

VALIDATION_FALLBACK: dict = {
    "verdict": "escalate",
    "confidence": 0.0,
    "reasoning": "Validation agent unavailable - escalating to cloud for safety",
}


class ValidationAgent:
    """Second-opinion validator called when trust is MEDIUM (no local state)."""

    def validate(self, decision: dict, context: dict | None = None) -> dict:
        context = context or {}
        user_message = f"""
Main agent decision to validate:
{json.dumps(decision, indent=2)}

Pipeline context:
- Trust Score: {context.get('trust_score', 'unknown')}
- Scenario: {context.get('scenario', 'unknown')}
- Critical: {context.get('critical', False)}
- Sanity Score: {context.get('sanity_score', 'unknown')}
- Raw Readings Summary: {json.dumps(context.get('raw_readings', {}), indent=2)}

Should this decision be confirmed or escalated to cloud?
Respond ONLY with JSON.
"""
        return safe_invoke(VALIDATION_PROMPT, user_message, VALIDATION_FALLBACK)

