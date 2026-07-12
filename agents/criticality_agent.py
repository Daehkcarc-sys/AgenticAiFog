"""Intelligence Layer — agricultural criticality classification agent.

Uses LLM reasoning to classify sensor readings into one of eight
canonical agricultural scenarios defined in ``CriticalityScenario``.
"""

from __future__ import annotations

import json

from llm_factory import safe_invoke
from models import CriticalityResult, CriticalityScenario

_VALID_SCENARIOS = "\n".join(
    f"{i}. {s.value}"
    for i, s in enumerate(CriticalityScenario, start=1)
)

CRITICALITY_PROMPT = f"""
You are an agricultural criticality detection agent deployed on a farm fog server.
Your classification helps decide whether to irrigate, alert, or escalate.

Given sensor readings and TinyML output, classify the situation into exactly one
of these agricultural scenarios:

{_VALID_SCENARIOS}

Soil moisture thresholds (typical loam soil):
- < 20%: severe water deficit
- 20-40%: moderate deficit
- 40-70%: optimal
- > 70%: excess / flooding risk

Temperature guidelines:
- < 0°C: frost risk
- 0-15°C: cool — slow growth
- 15-35°C: optimal for most crops
- 35-50°C: heat stress
- > 50°C: likely sensor malfunction or fire

Criticality rules:
- "Normal" means all readings are within expected ranges for healthy crops.
- "Water deficit" when soil moisture is consistently low.
- "Flooding" when soil moisture is very high with significant rainfall.
- "Fire or heat stress" when temperature exceeds crop-safe thresholds.
- "Crop disease risk" when humidity + temperature create fungal conditions.
- "Pest infestation risk" when warm + humid conditions persist.
- "Soil degradation" when pH or nutrients are far from optimal.
- "Equipment failure" when ANY sensor value is physically impossible
  (e.g. temp > 80°C, humidity > 100%, pH outside 0-14, negative moisture).

Flag as critical (critical=true) for any scenario other than "Normal".

Respond ONLY with this JSON, nothing else:
{{
    "critical": true or false,
    "scenario": "exact scenario name from the list above",
    "severity": "high or medium or low",
    "reasoning": "one sentence explaining the agricultural rationale with specific values"
}}
"""

CRITICALITY_FALLBACK: dict = {
    "passed": True,
    "critical": False,
    "scenario": CriticalityScenario.NORMAL.value,
    "severity": "low",
    "reasoning": "LLM unavailable - defaulting to Normal",
}

# Ensure the fallback scenario is valid
assert CRITICALITY_FALLBACK["scenario"] in {
    s.value for s in CriticalityScenario
}, "Fallback scenario must be a valid CriticalityScenario"


class CriticalityAgent:
    """LLM-based agricultural scenario classifier with deterministic pre-gate.

    Before invoking the LLM, a lightweight check determines whether the
    readings are clearly normal.  If all fields are within valid ranges
    and the TinyML confidence is high, the LLM is skipped entirely.
    """

    # If ALL checked fields pass sanity AND TinyML confidence is above
    # this threshold, skip the LLM and return "Normal".
    _SKIP_LLM_CONFIDENCE: float = 0.85

    def run(self, raw_readings: dict, tinyml_output: dict) -> CriticalityResult:
        # ── Deterministic pre-gate: skip LLM for clearly normal data ──
        if self._looks_normal(raw_readings, tinyml_output):
            return CriticalityResult(
                passed=True,
                critical=False,
                scenario=CriticalityScenario.NORMAL.value,
                severity="low",
                reasoning="All readings within normal ranges with high TinyML confidence",
            )

        # ── LLM classification ────────────────────────────
        user_message = (
            f"Sensor readings:\n{json.dumps(raw_readings, indent=2)}\n\n"
            f"TinyML output:\n{json.dumps(tinyml_output, indent=2)}\n\n"
            f"Classify the agricultural scenario.\n"
            f"Respond ONLY with JSON."
        )
        result = safe_invoke(CRITICALITY_PROMPT, user_message, CRITICALITY_FALLBACK)

        scenario = result.get("scenario", CriticalityScenario.NORMAL.value)
        valid_scenarios = {s.value for s in CriticalityScenario}
        if scenario not in valid_scenarios:
            scenario = CriticalityScenario.NORMAL.value

        return CriticalityResult(
            passed=True,
            critical=bool(result.get("critical", False)),
            scenario=scenario,
            severity=str(result.get("severity", "low")),
            reasoning=str(result.get("reasoning", "No reasoning provided")),
        )

    @staticmethod
    def _looks_normal(raw_readings: dict, tinyml_output: dict) -> bool:
        """Return True if readings are clearly normal — no LLM needed."""
        from config import VALID_RANGES

        confidence = tinyml_output.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or confidence < CriticalityAgent._SKIP_LLM_CONFIDENCE:
            return False

        # Require at least 4 core fields to be present and in-range
        core_fields = {"soil_moisture", "temperature", "humidity", "ph"}
        passed = 0
        for field in core_fields:
            value = raw_readings.get(field)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                return False
            min_val, max_val = VALID_RANGES.get(field, (float("-inf"), float("inf")))
            if min_val <= value <= max_val:
                passed += 1

        return passed >= 4
