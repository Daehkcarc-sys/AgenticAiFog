# pipeline.py
# Orchestrates all 6 agents in sequence
# Implements early exit at each stage to save compute

from agents.data_validation_agent import DataValidationAgent
from agents.timestamp_agent import TimestampAgent
from agents.trust_score_agent import TrustScoreAgent, EARLY_EXIT_THRESHOLD
from agents.value_sanity_agent import ValueSanityAgent
from agents.criticality_agent import CriticalityAgent
from agents.decision_agent import DecisionAgent
from action_handler import ActionHandler
from logger import FogLogger

class FogPipeline:

    def __init__(self):
        self.data_validator   = DataValidationAgent()
        self.timestamp_agent  = TimestampAgent()
        self.trust_scorer     = TrustScoreAgent()
        self.sanity_agent     = ValueSanityAgent()
        self.criticality_agent = CriticalityAgent()
        self.decision_agent   = DecisionAgent()
        self.action_handler   = ActionHandler()
        self.logger           = FogLogger()

    def run(self, sensor_data: dict) -> str:
        sensor_id    = sensor_data.get("sensor_id")
        raw_readings = sensor_data.get("raw_readings", {})
        tinyml_output = sensor_data.get("tinyml_output", {})

        # ── Agent 1: Data Validation ──────────────────────────
        v = self.data_validator.run(sensor_data)
        print(f"[Agent 1 - Validation] {'✓' if v['passed'] else '✗'} {v['reason']}")
        if not v["passed"]:
            return self._reject(sensor_id, v["reason"], 0.0)

        # ── Agent 2: Timestamp ────────────────────────────────
        t = self.timestamp_agent.run(sensor_data)
        print(f"[Agent 2 - Timestamp]  {'✓' if t['passed'] else '✗'} {t['reason']}")
        if not t["passed"]:
            return self._reject(sensor_id, t["reason"], 0.0)

        # ── Agent 3: Trust Score (early exit gate) ────────────
        ts = self.trust_scorer.run(t["freshness_score"], tinyml_output, raw_readings)
        trust_score = ts["trust_score"]
        trust_level = self._get_trust_level(trust_score)
        print(f"[Agent 3 - Trust]      {'✓' if ts['passed'] else '✗'} Score: {trust_score} | Level: {trust_level}")
        if not ts["passed"]:
            return self._reject(sensor_id, ts["reason"], trust_score)

        # ── Agent 4: Value Sanity ─────────────────────────────
        s = self.sanity_agent.run(raw_readings)
        print(f"[Agent 4 - Sanity]     ✓ {s['reason']}")

        # ── Agent 5: Criticality ──────────────────────────────
        c = self.criticality_agent.run(raw_readings, tinyml_output)
        print(f"[Agent 5 - Criticality] {'⚠' if c['critical'] else '✓'} Scenario: {c['scenario']} | Severity: {c['severity']}")

        # ── Agent 6: Decision ─────────────────────────────────
        context = {
            "sensor_id":           sensor_id,
            "trust_score":         trust_score,
            "trust_level":         trust_level,
            "sanity_score":        s["sanity_score"],
            "failed_fields":       s.get("failed_fields", []),
            "critical":            c["critical"],
            "scenario":            c["scenario"],
            "severity":            c["severity"],
            "tinyml_recommendation": tinyml_output.get("recommended_action")
        }

        d = self.decision_agent.run(context)
        print(f"[Agent 6 - Decision]   → {d['decision']} | Action: {d['action_required']}")

        result = self.action_handler.route(
    d["action_required"], 
    d, 
    trust_level,
    context={
        **context,
        "raw_readings": raw_readings
    }
)

        self.logger.log(
            sensor_id=sensor_id,
            trust_score=trust_score,
            trust_level=trust_level,
            decision=d,
            result=result,
            scenario=c["scenario"],
            critical=c["critical"]
        )

        return result

    def _get_trust_level(self, score: float) -> str:
        if score >= 0.8:
            return "HIGH"
        elif score >= 0.5:
            return "MEDIUM"
        else:
            return "LOW"

    def _reject(self, sensor_id: str, reason: str, score: float) -> str:
        result = self.action_handler.reject_and_alert(
            reason,
            {"sensor_id": sensor_id}
        )
        self.logger.log(
            sensor_id=sensor_id,
            trust_score=score,
            trust_level="LOW",
            decision={"reasoning": reason},
            result=result,
            scenario="N/A",
            critical=False
        )
        return result