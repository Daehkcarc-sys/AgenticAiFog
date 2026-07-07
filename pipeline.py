from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

from action_handler import ActionHandler
from agents import (
    CriticalityAgent,
    DataValidationAgent,
    DecisionAgent,
    TimestampAgent,
    TrustScoreAgent,
    ValueSanityAgent,
)
from config import TRUST_LEVEL_THRESHOLDS
from contracts import PipelineContext
from logger import FogLogger
from metrics import PipelineMetrics
from models import TrustLevel


class FogPipeline:

    def __init__(self, metrics: PipelineMetrics | None = None):
        self.data_validator = DataValidationAgent()
        self.timestamp_agent = TimestampAgent()
        self.trust_scorer = TrustScoreAgent()
        self.sanity_agent = ValueSanityAgent()
        self.criticality_agent = CriticalityAgent()
        self.decision_agent = DecisionAgent()
        self.action_handler = ActionHandler()
        self.logger = FogLogger()
        self.metrics = metrics

    def run(self, sensor_data: dict) -> str:
        sensor_id = sensor_data.get("sensor_id")
        raw_readings = sensor_data.get("raw_readings", {})
        tinyml_output = sensor_data.get("tinyml_output", {})

        m = self.metrics
        start_time = perf_counter()

        with (m.measure("data_validation") if m else _null_context()):
            v = self.data_validator.run(sensor_data)
        print(f"[Agent 1 - Validation] {'✓' if v['passed'] else '✗'} {v['reason']}")
        if not v["passed"]:
            return self._reject(sensor_id, v["reason"], 0.0)

        with (m.measure("timestamp") if m else _null_context()):
            t = self.timestamp_agent.run(sensor_data)
        print(f"[Agent 2 - Timestamp]  {'✓' if t['passed'] else '✗'} {t['reason']}")
        if not t["passed"]:
            return self._reject(sensor_id, t["reason"], 0.0)

        with (m.measure("trust_score") if m else _null_context()):
            ts = self.trust_scorer.run(t["freshness_score"], tinyml_output, raw_readings)
        trust_score = ts["trust_score"]
        trust_level = self._get_trust_level(trust_score)
        print(f"[Agent 3 - Trust]      {'✓' if ts['passed'] else '✗'} Score: {trust_score} | Level: {trust_level}")
        if not ts["passed"]:
            return self._reject(sensor_id, ts["reason"], trust_score)

        with (m.measure("value_sanity") if m else _null_context()):
            s = self.sanity_agent.run(raw_readings)
        print(f"[Agent 4 - Sanity]     ✓ {s['reason']}")

        with (m.measure("criticality") if m else _null_context()):
            c = self.criticality_agent.run(raw_readings, tinyml_output)
        print(f"[Agent 5 - Criticality] {'⚠' if c['critical'] else '✓'} Scenario: {c['scenario']} | Severity: {c['severity']}")

        context: PipelineContext = {
            "sensor_id": sensor_id,
            "trust_score": trust_score,
            "trust_level": trust_level,
            "sanity_score": s["sanity_score"],
            "failed_fields": s.get("failed_fields", []),
            "critical": c["critical"],
            "scenario": c["scenario"],
            "severity": c["severity"],
            "tinyml_recommendation": tinyml_output.get("recommended_action"),
        }

        with (m.measure("decision") if m else _null_context()):
            d = self.decision_agent.run(context)
        print(f"[Agent 6 - Decision]   → {d['decision']} | Action: {d['action_required']}")

        result = self.action_handler.route(
            d["action_required"],
            d,
            trust_level,
            context={**context, "raw_readings": raw_readings},
        )

        pipeline_latency_ms = round((perf_counter() - start_time) * 1000, 2)
        self.logger.log(
            sensor_id=sensor_id,
            trust_score=trust_score,
            trust_level=trust_level,
            decision=d,
            result=result,
            scenario=c["scenario"],
            critical=c["critical"],
            additional={"pipeline_latency_ms": pipeline_latency_ms},
        )

        if m is not None:
            m.record_reading(
                trust_score=trust_score,
                scenario=c["scenario"],
                decision=d["decision"],
                action=d["action_required"],
                result=result,
            )

        return result

    def _get_trust_level(self, score: float) -> TrustLevel:
        if score >= TRUST_LEVEL_THRESHOLDS["HIGH"]:
            return TrustLevel.HIGH
        if score >= TRUST_LEVEL_THRESHOLDS["MEDIUM"]:
            return TrustLevel.MEDIUM
        return TrustLevel.LOW

    def _reject(self, sensor_id: str, reason: str, score: float) -> str:
        result = self.action_handler.reject_and_alert(reason, {"sensor_id": sensor_id})
        self.logger.log(
            sensor_id=sensor_id,
            trust_score=score,
            trust_level=TrustLevel.LOW,
            decision={"reasoning": reason},
            result=result,
            scenario="N/A",
            critical=False,
            additional={"pipeline_latency_ms": 0.0},
        )
        return result


@contextmanager
def _null_context() -> Iterator[None]:
    """A no-op context manager used when no metrics collector is attached."""
    yield
