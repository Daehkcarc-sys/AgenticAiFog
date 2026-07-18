"""Intelligence Layer - local-first agricultural criticality classifier.

The agent keeps the existing ``run(raw_readings, tinyml_output, context)``
interface, but resolves criticality locally first. Remote LLM fallback is
optional and only used for ambiguous cases when explicitly enabled.
"""

from __future__ import annotations

import json
from typing import Any

from config import (
    CRITICALITY_AMBIGUITY_MARGIN,
    CRITICALITY_ENABLE_REMOTE_FALLBACK,
    CRITICALITY_MODE,
    VALID_RANGES,
)
from models import CriticalityResult, CriticalityScenario

_VALID_SCENARIOS = "\n".join(
    f"{i}. {s.value}"
    for i, s in enumerate(CriticalityScenario, start=1)
)

CRITICALITY_PROMPT = f"""
You are an agricultural criticality detection agent deployed on a farm fog server.
Your classification helps decide whether to irrigate, alert, or escalate.

Given sensor readings, TinyML output, and context, classify the situation into
exactly one of these agricultural scenarios:

{_VALID_SCENARIOS}

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
    "reasoning": "LLM unavailable - using safe Normal fallback",
}


class CriticalityAgent:
    """Local-first scenario classifier with optional remote fallback."""

    _SKIP_LLM_CONFIDENCE: float = 0.85

    def run(
        self,
        raw_readings: dict,
        tinyml_output: dict,
        context: dict | None = None,
    ) -> CriticalityResult:
        context = context or {}
        scores, evidence = self._score_scenarios(raw_readings, tinyml_output, context)
        best, best_score, second_score = self._rank(scores)

        if best_score <= 0:
            return CriticalityResult(
                passed=True,
                critical=False,
                scenario=CriticalityScenario.NORMAL.value,
                severity="low",
                reasoning="No local criticality indicators detected",
            )

        ambiguous = (best_score - second_score) <= CRITICALITY_AMBIGUITY_MARGIN
        if self._should_use_remote_fallback(ambiguous):
            return self._remote_fallback(raw_readings, tinyml_output, context)

        reason = "; ".join(evidence.get(best, [])) or f"{best.value} selected by local classifier"
        if ambiguous:
            reason = f"{reason}; local classifier selected best available scenario under ambiguity"

        return CriticalityResult(
            passed=True,
            critical=best != CriticalityScenario.NORMAL,
            scenario=best.value,
            severity=self._severity(best, best_score, context),
            reasoning=reason,
        )

    def _should_use_remote_fallback(self, ambiguous: bool) -> bool:
        if CRITICALITY_MODE.lower() == "local_only":
            return False
        return ambiguous and CRITICALITY_ENABLE_REMOTE_FALLBACK

    def _score_scenarios(
        self,
        readings: dict[str, Any],
        tinyml_output: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[dict[CriticalityScenario, int], dict[CriticalityScenario, list[str]]]:
        scores = {scenario: 0 for scenario in CriticalityScenario}
        evidence = {scenario: [] for scenario in CriticalityScenario}

        self._score_equipment(readings, context, scores, evidence)
        self._score_water(readings, tinyml_output, context, scores, evidence)
        self._score_heat(readings, context, scores, evidence)
        self._score_biology(readings, scores, evidence)
        self._score_soil(readings, scores, evidence)

        if all(score == 0 for scenario, score in scores.items() if scenario != CriticalityScenario.NORMAL):
            scores[CriticalityScenario.NORMAL] = 1
            evidence[CriticalityScenario.NORMAL].append("all local risk scores are zero")

        return scores, evidence

    @staticmethod
    def _score_equipment(
        readings: dict[str, Any],
        context: dict[str, Any],
        scores: dict[CriticalityScenario, int],
        evidence: dict[CriticalityScenario, list[str]],
    ) -> None:
        for field, (min_val, max_val) in VALID_RANGES.items():
            value = readings.get(field)
            if value is None:
                continue
            if not isinstance(value, (int, float)):
                scores[CriticalityScenario.EQUIPMENT_FAILURE] += 8
                evidence[CriticalityScenario.EQUIPMENT_FAILURE].append(f"{field} is non-numeric")
            elif value < min_val or value > max_val:
                scores[CriticalityScenario.EQUIPMENT_FAILURE] += 8
                evidence[CriticalityScenario.EQUIPMENT_FAILURE].append(
                    f"{field}={value} outside [{min_val}, {max_val}]"
                )

        anomalies = context.get("multi_level_anomalies", {})
        physical = anomalies.get("physical", [])
        statistical = anomalies.get("statistical", [])
        if physical:
            scores[CriticalityScenario.EQUIPMENT_FAILURE] += 4
            evidence[CriticalityScenario.EQUIPMENT_FAILURE].append(
                f"physical anomalies: {', '.join(physical)}"
            )
        if statistical:
            scores[CriticalityScenario.EQUIPMENT_FAILURE] += 1
            evidence[CriticalityScenario.EQUIPMENT_FAILURE].append(
                f"statistical anomalies: {', '.join(statistical)}"
            )

    @staticmethod
    def _score_water(
        readings: dict[str, Any],
        tinyml_output: dict[str, Any],
        context: dict[str, Any],
        scores: dict[CriticalityScenario, int],
        evidence: dict[CriticalityScenario, list[str]],
    ) -> None:
        moisture = readings.get("soil_moisture")
        rainfall = readings.get("rainfall")
        action = str(tinyml_output.get("recommended_action", "")).lower()
        moisture_trend = context.get("trends", {}).get("soil_moisture")

        if isinstance(moisture, (int, float)):
            if moisture < 20:
                scores[CriticalityScenario.WATER_DEFICIT] += 4
                evidence[CriticalityScenario.WATER_DEFICIT].append(
                    f"soil_moisture={moisture}% below severe deficit threshold"
                )
            elif moisture < 40:
                scores[CriticalityScenario.WATER_DEFICIT] += 2
                evidence[CriticalityScenario.WATER_DEFICIT].append(
                    f"soil_moisture={moisture}% below optimal range"
                )
            elif moisture > 80:
                scores[CriticalityScenario.FLOODING] += 4
                evidence[CriticalityScenario.FLOODING].append(
                    f"soil_moisture={moisture}% indicates saturated soil"
                )
            elif moisture > 70:
                scores[CriticalityScenario.FLOODING] += 2
                evidence[CriticalityScenario.FLOODING].append(
                    f"soil_moisture={moisture}% above optimal range"
                )

        if isinstance(moisture, (int, float)) and isinstance(rainfall, (int, float)):
            if moisture < 25 and rainfall == 0:
                scores[CriticalityScenario.WATER_DEFICIT] += 2
                evidence[CriticalityScenario.WATER_DEFICIT].append("low moisture with no rainfall")
            if moisture > 70 and rainfall > 50:
                scores[CriticalityScenario.FLOODING] += 3
                evidence[CriticalityScenario.FLOODING].append("high moisture with heavy rainfall")

        if isinstance(moisture_trend, (int, float)):
            if moisture_trend < -2:
                scores[CriticalityScenario.WATER_DEFICIT] += 1
                evidence[CriticalityScenario.WATER_DEFICIT].append(
                    f"soil moisture falling {moisture_trend:+.2f} per reading"
                )
            elif moisture_trend > 2:
                scores[CriticalityScenario.FLOODING] += 1
                evidence[CriticalityScenario.FLOODING].append(
                    f"soil moisture rising {moisture_trend:+.2f} per reading"
                )

        if action == "irrigate" and isinstance(moisture, (int, float)) and moisture < 40:
            scores[CriticalityScenario.WATER_DEFICIT] += 1
            evidence[CriticalityScenario.WATER_DEFICIT].append("TinyML recommends irrigate")
        elif action == "stop_irrigation" and isinstance(moisture, (int, float)) and moisture > 70:
            scores[CriticalityScenario.FLOODING] += 1
            evidence[CriticalityScenario.FLOODING].append("TinyML recommends stop_irrigation")

    @staticmethod
    def _score_heat(
        readings: dict[str, Any],
        context: dict[str, Any],
        scores: dict[CriticalityScenario, int],
        evidence: dict[CriticalityScenario, list[str]],
    ) -> None:
        temperature = readings.get("temperature")
        vpd = context.get("derived_features", {}).get("vapor_pressure_deficit_kpa")

        if isinstance(temperature, (int, float)):
            if temperature > 50:
                scores[CriticalityScenario.HEAT_STRESS] += 5
                evidence[CriticalityScenario.HEAT_STRESS].append(
                    f"temperature={temperature}C may indicate fire or sensor fault"
                )
            elif temperature > 35:
                scores[CriticalityScenario.HEAT_STRESS] += 3
                evidence[CriticalityScenario.HEAT_STRESS].append(
                    f"temperature={temperature}C exceeds crop-safe range"
                )
            elif temperature < 0:
                scores[CriticalityScenario.HEAT_STRESS] += 2
                evidence[CriticalityScenario.HEAT_STRESS].append(
                    f"temperature={temperature}C indicates frost risk"
                )

        if isinstance(vpd, (int, float)) and vpd >= 2.0:
            scores[CriticalityScenario.HEAT_STRESS] += 2
            evidence[CriticalityScenario.HEAT_STRESS].append(
                f"VPD={vpd} kPa indicates high evaporative demand"
            )

    @staticmethod
    def _score_biology(
        readings: dict[str, Any],
        scores: dict[CriticalityScenario, int],
        evidence: dict[CriticalityScenario, list[str]],
    ) -> None:
        temperature = readings.get("temperature")
        humidity = readings.get("humidity")
        leaf_wetness = readings.get("leaf_wetness")

        if not isinstance(temperature, (int, float)) or not isinstance(humidity, (int, float)):
            return

        if humidity > 85 and 18 <= temperature <= 32:
            scores[CriticalityScenario.DISEASE_RISK] += 4
            evidence[CriticalityScenario.DISEASE_RISK].append(
                f"humidity={humidity}% and temperature={temperature}C create fungal conditions"
            )
        if isinstance(leaf_wetness, (int, float)) and leaf_wetness > 80:
            scores[CriticalityScenario.DISEASE_RISK] += 1
            evidence[CriticalityScenario.DISEASE_RISK].append(f"leaf_wetness={leaf_wetness}% is high")

        if humidity >= 65 and 24 <= temperature <= 34:
            scores[CriticalityScenario.PEST_INFESTATION] += 3
            evidence[CriticalityScenario.PEST_INFESTATION].append(
                f"warm humid conditions humidity={humidity}%, temperature={temperature}C"
            )

    @staticmethod
    def _score_soil(
        readings: dict[str, Any],
        scores: dict[CriticalityScenario, int],
        evidence: dict[CriticalityScenario, list[str]],
    ) -> None:
        ph = readings.get("ph")
        salinity = readings.get("salinity")
        nutrients = {
            "N": readings.get("nitrogen"),
            "P": readings.get("phosphorus"),
            "K": readings.get("potassium"),
        }

        if isinstance(ph, (int, float)):
            if ph < 5.5 or ph > 8.0:
                scores[CriticalityScenario.SOIL_DEGRADATION] += 3
                evidence[CriticalityScenario.SOIL_DEGRADATION].append(
                    f"ph={ph} outside crop comfort band"
                )
            elif ph < 6.0 or ph > 7.5:
                scores[CriticalityScenario.SOIL_DEGRADATION] += 1
                evidence[CriticalityScenario.SOIL_DEGRADATION].append(f"ph={ph} is borderline")

        low_nutrients = [
            name for name, value in nutrients.items()
            if isinstance(value, (int, float)) and value < 20
        ]
        if low_nutrients:
            scores[CriticalityScenario.SOIL_DEGRADATION] += len(low_nutrients)
            evidence[CriticalityScenario.SOIL_DEGRADATION].append(
                f"low nutrients: {', '.join(low_nutrients)}"
            )

        if isinstance(salinity, (int, float)) and salinity > 8:
            scores[CriticalityScenario.SOIL_DEGRADATION] += 2
            evidence[CriticalityScenario.SOIL_DEGRADATION].append(
                f"salinity={salinity} dS/m is high"
            )

    @staticmethod
    def _rank(
        scores: dict[CriticalityScenario, int]
    ) -> tuple[CriticalityScenario, int, int]:
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        return best, best_score, second_score

    @staticmethod
    def _severity(
        scenario: CriticalityScenario,
        score: int,
        context: dict[str, Any],
    ) -> str:
        anomaly_severity = context.get("multi_level_anomalies", {}).get("severity")
        if (
            scenario == CriticalityScenario.EQUIPMENT_FAILURE
            or anomaly_severity == "high"
            or score >= 5
        ):
            return "high"
        if score >= 3 or anomaly_severity == "medium":
            return "medium"
        return "low"

    def _remote_fallback(
        self,
        raw_readings: dict,
        tinyml_output: dict,
        context: dict,
    ) -> CriticalityResult:
        from llm_factory import safe_invoke

        user_message = (
            f"Sensor readings:\n{json.dumps(raw_readings, indent=2)}\n\n"
            f"TinyML output:\n{json.dumps(tinyml_output, indent=2)}\n\n"
            f"Context layer:\n{json.dumps(context, indent=2)}\n\n"
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
            critical=bool(result.get("critical", scenario != CriticalityScenario.NORMAL.value)),
            scenario=scenario,
            severity=str(result.get("severity", "low")),
            reasoning=str(result.get("reasoning", "No reasoning provided")),
        )
