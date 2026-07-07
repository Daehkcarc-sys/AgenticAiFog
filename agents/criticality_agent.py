from __future__ import annotations

import json

from llm_factory import safe_invoke
from models import CriticalityScenario

_VALID_SCENARIOS = "\n".join(
    f"{i}. {s.value}"
    for i, s in enumerate(CriticalityScenario, start=1)
)

CRITICALITY_PROMPT = f"""
You are an agricultural criticality detection agent on a farm fog server.
Given sensor readings, classify the situation into exactly one of these scenarios:
{_VALID_SCENARIOS}

Respond ONLY with this JSON, nothing else:
{{
    "critical": true or false,
    "scenario": "exact scenario name from the list above",
    "severity": "high or medium or low",
    "reasoning": "one sentence explanation"
}}
"""

CRITICALITY_FALLBACK: dict = {
    "passed": True,
    "critical": False,
    "scenario": "Normal",
    "severity": "low",
    "reasoning": "LLM unavailable - defaulting to Normal",
}


class CriticalityAgent:
    """LLM-based agricultural scenario classifier (no local state)."""

    def run(self, raw_readings: dict, tinyml_output: dict) -> dict:
        user_message = f"""
Sensor readings:
{json.dumps(raw_readings, indent=2)}

TinyML output:
{json.dumps(tinyml_output, indent=2)}

Classify the agricultural scenario.
Respond ONLY with JSON.
"""
        result = safe_invoke(CRITICALITY_PROMPT, user_message, CRITICALITY_FALLBACK)
        result["passed"] = True
        return result
