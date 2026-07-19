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
    "critical": True,
    "scenario": CriticalityScenario.EQUIPMENT_FAILURE.value,
    "severity": "medium",
    "reasoning": "Unclassified anomaly while LLM unavailable - conservative escalation",
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

    def run(
        self,
        raw_readings: dict,
        tinyml_output: dict,
        context: dict | None = None,
    ) -> CriticalityResult:
        context = context or {}
        # Clear safety-relevant cases are resolved locally. These rules are
        # also the primary classifier during explicit offline execution.
        rule_result = self._classify_with_rules(raw_readings)
        if rule_result is not None:
            return rule_result

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
        from config import NORMAL_OPERATING_RANGES

        confidence = tinyml_output.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or confidence < CriticalityAgent._SKIP_LLM_CONFIDENCE:
            return False

        # Require at least 4 core fields to be present and in-range
        core_fields = set(NORMAL_OPERATING_RANGES)
        passed = 0
        for field in core_fields:
            value = raw_readings.get(field)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                return False
            min_val, max_val = NORMAL_OPERATING_RANGES[field]
            if min_val <= value <= max_val:
                passed += 1

        return passed >= 4

    @staticmethod
    def _classify_with_rules(raw_readings: dict) -> CriticalityResult | None:
        """Classify clear agricultural events without an LLM."""
        from config import VALID_RANGES

        for field, (minimum, maximum) in VALID_RANGES.items():
            value = raw_readings.get(field)
            if isinstance(value, (int, float)) and not minimum <= value <= maximum:
                return CriticalityResult(
                    passed=True,
                    critical=True,
                    scenario=CriticalityScenario.EQUIPMENT_FAILURE.value,
                    severity="high",
                    reasoning=f"{field}={value} is outside its physical range",
                )

        moisture = raw_readings.get("soil_moisture")
        temperature = raw_readings.get("temperature")
        humidity = raw_readings.get("humidity")
        ph = raw_readings.get("ph")

        if isinstance(temperature, (int, float)) and temperature > 35:
            return CriticalityResult(
                passed=True,
                critical=True,
                scenario=CriticalityScenario.HEAT_STRESS.value,
                severity="high" if temperature >= 45 else "medium",
                reasoning=f"Temperature {temperature}C exceeds the crop-safe range",
            )

        if isinstance(moisture, (int, float)) and moisture < 40:
            return CriticalityResult(
                passed=True,
                critical=True,
                scenario=CriticalityScenario.WATER_DEFICIT.value,
                severity="high" if moisture < 20 else "medium",
                reasoning=f"Soil moisture {moisture}% indicates water deficit",
            )

        if isinstance(moisture, (int, float)) and moisture > 70:
            return CriticalityResult(
                passed=True,
                critical=True,
                scenario=CriticalityScenario.FLOODING.value,
                severity="high" if moisture >= 85 else "medium",
                reasoning=f"Soil moisture {moisture}% indicates excess water",
            )

        if isinstance(ph, (int, float)) and not 5.5 <= ph <= 8.0:
            return CriticalityResult(
                passed=True,
                critical=True,
                scenario=CriticalityScenario.SOIL_DEGRADATION.value,
                severity="medium",
                reasoning=f"Soil pH {ph} is outside the conservative operating range",
            )

        if (
            isinstance(humidity, (int, float))
            and isinstance(temperature, (int, float))
            and humidity > 85
            and 18 <= temperature <= 35
        ):
            return CriticalityResult(
                passed=True,
                critical=True,
                scenario=CriticalityScenario.DISEASE_RISK.value,
                severity="medium",
                reasoning=(
                    f"Humidity {humidity}% at {temperature}C creates disease-favorable conditions"
                ),
            )

        return None
