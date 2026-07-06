# trust_scorer.py
# Fog layer trust verification - Zero Trust approach
# Every reading must be verified before the agent acts on it

from datetime import datetime, timezone

# Will need to check for the real sensor ids in actual deployment
# In production this calls the Cryptographic Identity & Attestation block (Figure 1)
SENSOR_REGISTRY = [
    "SENSOR_001",
    "SENSOR_002",
    "SENSOR_003"
]

# Fake values for now - thinking of adding another agent which does the research for these
VALID_RANGES = {
    # field:         (min, max)
    "soil_moisture": (0, 100),
    "temperature":   (-20, 60),
    "humidity":      (0, 100),
    "rainfall":      (0, 500),
    "ph":            (0, 14),
    "nitrogen":      (0, 500),
    "phosphorus":    (0, 500),
    "potassium":     (0, 500),
}

WEIGHTS = {
    "identity":    0.35,
    "freshness":   0.15,
    "sanity":      0.25,
    "consistency": 0.25,
}

class TrustScorer:

    def __init__(self, freshness_limit_seconds: int = 300):
        # Zero Trust: we define upfront how old a reading can be
        # 300 seconds = 5 minutes, anything older is suspicious in real-time farming
        self.freshness_limit = freshness_limit_seconds

    def check_identity(self, sensor_id: str) -> float:
        # Zero Trust principle: unknown source = zero trust, full stop
        # .upper() prevents case-mismatch bypass attacks
        # In production this calls Cryptographic Identity & Attestation block (Figure 1)
        if sensor_id.upper() in SENSOR_REGISTRY:
            return 1.0
        return 0.0

    def check_freshness(self, timestamp: str) -> float:
        # Defends against replay attacks - attacker resends old valid data
        # Sharp drop after freshness_limit because stale data in IoT
        # usually means disconnection or active replay, not just slowness
        try:
            reading_time = datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - reading_time).total_seconds()

            if age_seconds < 60:
                return 1.0
            elif age_seconds < 180:
                return 0.8
            elif age_seconds < self.freshness_limit:  # 300s
                return 0.6
            elif age_seconds < 600:
                return 0.3
            else:
                # replay attacks are spooky :')
                return 0.0

        except ValueError:
            # malformed timestamp is itself suspicious
            return 0.0

    def check_value_sanity(self, readings: dict) -> float:
        # Proportional scoring - one bad sensor shouldn't kill valid readings
        # Only checks raw sensor values, not derived features
        # (derived features are validated indirectly through their raw inputs)
        # isinstance check protects against string values crashing the scorer
        # (crashing the trust scorer is itself an attack vector)
        fields_checked = 0
        fields_passed = 0

        for field, (min_val, max_val) in VALID_RANGES.items():
            if field in readings:
                fields_checked += 1
                value = readings[field]

                if isinstance(value, (int, float)) and min_val <= value <= max_val:
                    fields_passed += 1

        # none of our expected fields present = very suspicious
        if fields_checked == 0:
            return 0.0

        return fields_passed / fields_checked

    def check_consistency(self, readings: dict, tinyml_output: dict) -> float:
        # High confidence + inconsistent data = MORE suspicious
        # Attacker spoofing TinyML would always send high confidence to look legitimate
        action = tinyml_output.get("recommended_action", "").lower()
        confidence = tinyml_output.get("confidence", 0.5)
        soil_moisture = readings.get("soil_moisture", None)

        if soil_moisture is None:
            return 0.5  # missing field, neutral score

        if action == "irrigate":
            if soil_moisture > 80:
                # clear inconsistency - high confidence makes it more suspicious
                base_score = 0.4
                return base_score * (1 - confidence * 0.5)
            elif soil_moisture > 50:
                # mild inconsistency
                return 0.65
            else:
                # consistent
                return 1.0

        elif action == "no_action":
            if soil_moisture < 20:
                # clear inconsistency
                base_score = 0.4
                return base_score * (1 - confidence * 0.5)
            elif soil_moisture < 40:
                # mild inconsistency
                return 0.65
            else:
                # consistent
                return 1.0

        # unknown action from TinyML is itself suspicious
        return 0.3

    def score(self, sensor_data: dict) -> float:
        identity = self.check_identity(sensor_data.get("sensor_id", ""))

        
        if identity == 0.0:
            return 0.0

        freshness   = self.check_freshness(sensor_data.get("timestamp", ""))
        sanity      = self.check_value_sanity(sensor_data.get("raw_readings", {}))
        consistency = self.check_consistency(
                        sensor_data.get("raw_readings", {}),
                        sensor_data.get("tinyml_output", {})
                    )



        final_score = (
            identity    * WEIGHTS["identity"]    +
            freshness   * WEIGHTS["freshness"]   +
            sanity      * WEIGHTS["sanity"]      +
            consistency * WEIGHTS["consistency"]
        )


        return round(final_score, 3)

    def is_trusted(self, score: float) -> bool:
        # threshold at 0.6 - below this fog agent escalates or rejects
        return score >= 0.6

    def get_trust_level(self, score: float) -> str:
        # HIGH  → act locally, send command back to edge
        # MEDIUM → goes to agentic decision loop + validation agent (friend's agent)
        # LOW   → local anomaly detection + alert + notify cloud
        if score >= 0.8:
            return "HIGH"
        elif score >= 0.6:
            return "MEDIUM"
        else:
            return "LOW"