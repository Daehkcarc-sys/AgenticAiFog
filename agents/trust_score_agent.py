from __future__ import annotations

from config import EARLY_EXIT_THRESHOLD
from models import TrustScoreResult

WEIGHTS = {
    "identity": 0.35,
    "freshness": 0.25,
    "consistency": 0.40,
}


class TrustScoreAgent:
    """Trust Layer — composite reliability score for Fog decision gating.

    Combines identity (35%), freshness (25%), and TinyML consistency
    (40%) into a single score.  This is a lightweight heuristic suitable
    for real-time Fog assessment on Industrial PC / Jetson-class hardware,
    not a formal trust calculus.
    """

    def run(
        self,
        freshness_score: float,
        tinyml_output: dict,
        raw_readings: dict,
    ) -> TrustScoreResult:
        identity_score = 1.0  # already verified by DataValidationAgent
        consistency_score = self._check_consistency(raw_readings, tinyml_output)

        score = round(
            identity_score * WEIGHTS["identity"]
            + freshness_score * WEIGHTS["freshness"]
            + consistency_score * WEIGHTS["consistency"],
            3,
        )

        passed = score >= EARLY_EXIT_THRESHOLD
        reason = (
            "Trust score above threshold"
            if passed
            else f"Trust score too low: {score}"
        )

        return TrustScoreResult(
            passed=passed,
            trust_score=score,
            consistency_score=consistency_score,
            reason=reason,
        )

    def _check_consistency(self, readings: dict, tinyml_output: dict) -> float:
        action = tinyml_output.get("recommended_action", "").lower()
        confidence = tinyml_output.get("confidence", 0.5)
        soil_moisture = readings.get("soil_moisture")

        if soil_moisture is None:
            return 0.5

        if action == "irrigate":
            if soil_moisture > 80:
                return 0.4 * (1 - confidence * 0.5)
            if soil_moisture > 50:
                return 0.65
            return 1.0

        if action == "no_action":
            if soil_moisture < 20:
                return 0.4 * (1 - confidence * 0.5)
            if soil_moisture < 40:
                return 0.65
            return 1.0

        return 0.3
