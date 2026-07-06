# Agent 3: Trust Score Agent (moved to position 3 per supervisor)
# Early exit gate - reject before wasting compute on sanity/criticality
# Rules-based only - weighted average of available scores so far

WEIGHTS = {
    "identity":    0.35,
    "freshness":   0.25,
    "consistency": 0.40,
}

EARLY_EXIT_THRESHOLD = 0.5

class TrustScoreAgent:

    def run(self, freshness_score: float, tinyml_output: dict, 
            raw_readings: dict) -> dict:

        # identity passed agent 1 so its always 1.0 here
        identity_score = 1.0

        # consistency check - high confidence + wrong data = suspicious
        consistency_score = self._check_consistency(raw_readings, tinyml_output)

        # early trust score from available info
        score = round(
            identity_score    * WEIGHTS["identity"]    +
            freshness_score   * WEIGHTS["freshness"]   +
            consistency_score * WEIGHTS["consistency"],
            3
        )

        passed = score >= EARLY_EXIT_THRESHOLD

        return {
            "passed": passed,
            "trust_score": score,
            "consistency_score": consistency_score,
            "reason": "Trust score above threshold" if passed else f"Trust score too low: {score}"
        }

    def _check_consistency(self, readings: dict, tinyml_output: dict) -> float:
        action = tinyml_output.get("recommended_action", "").lower()
        confidence = tinyml_output.get("confidence", 0.5)
        soil_moisture = readings.get("soil_moisture", None)

        if soil_moisture is None:
            return 0.5

        if action == "irrigate":
            if soil_moisture > 80:
                return 0.4 * (1 - confidence * 0.5)
            elif soil_moisture > 50:
                return 0.65
            else:
                return 1.0

        elif action == "no_action":
            if soil_moisture < 20:
                return 0.4 * (1 - confidence * 0.5)
            elif soil_moisture < 40:
                return 0.65
            else:
                return 1.0

        return 0.3