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
from config import ACTION_WHITELIST, TRUST_LEVEL_THRESHOLDS
from contracts import PipelineContext
from decision_cache import DecisionCache
from llm_factory import connectivity_stats
from logger import FogLogger
from metrics import PipelineMetrics
from models import TrustLevel


class FogPipeline:
    """Trust-oriented multi-agent fog pipeline.

    Wires together the Trust Layer (Agents 1-4), Intelligence Layer
    (Agents 5-6 with cache), and Enforcement Layer (ActionHandler).

    Args:
        metrics: Optional ``PipelineMetrics`` for benchmarking.
        cache: Optional ``DecisionCache`` for LLM call reduction.
    """

    def __init__(
        self,
        metrics: PipelineMetrics | None = None,
        cache: DecisionCache | None = None,
    ):
        self.data_validator = DataValidationAgent()
        self.timestamp_agent = TimestampAgent()
        self.trust_scorer = TrustScoreAgent()
        self.sanity_agent = ValueSanityAgent()
        self.criticality_agent = CriticalityAgent()
        self.decision_agent = DecisionAgent(cache=cache)
        self.action_handler = ActionHandler()
        self.logger = FogLogger()
        self.metrics = metrics
        self._cache = cache

    def run(self, sensor_data: dict) -> str:
        sensor_id = sensor_data.get("sensor_id")
        raw_readings = sensor_data.get("raw_readings", {})
        tinyml_output = sensor_data.get("tinyml_output", {})

        m = self.metrics
        start_time = perf_counter()

        # ── Trust Layer ───────────────────────────────────
        with (m.measure("data_validation") if m else _null_context()):
            v = self.data_validator.run(sensor_data)
        print(f"[Agent 1 - Validation] {'PASS' if v.passed else 'FAIL'} {v.reason}")
        if not v.passed:
            return self._reject(sensor_id, v.reason, 0.0, start_time)

        with (m.measure("timestamp") if m else _null_context()):
            t = self.timestamp_agent.run(sensor_data)
        print(f"[Agent 2 - Timestamp]  {'PASS' if t.passed else 'FAIL'} {t.reason}")
        if not t.passed:
            return self._reject(sensor_id, t.reason, 0.0, start_time)

        with (m.measure("trust_score") if m else _null_context()):
            ts = self.trust_scorer.run(
                t.freshness_score, tinyml_output, raw_readings
            )
        trust_score = ts.trust_score
        trust_level = self._get_trust_level(trust_score)
        print(
            f"[Agent 3 - Trust]      {'PASS' if ts.passed else 'FAIL'} "
            f"Score: {trust_score} | Level: {trust_level}"
        )
        if not ts.passed:
            return self._reject(sensor_id, ts.reason, trust_score, start_time)

        with (m.measure("value_sanity") if m else _null_context()):
            s = self.sanity_agent.run(raw_readings, tinyml_output)
        print(f"[Agent 4 - Sanity]     {'PASS' if s.passed else 'FAIL'} {s.reason}")
        if not s.passed:
            return self._reject(sensor_id, s.reason, trust_score, start_time)

        # ── Intelligence Layer ────────────────────────────
        with (m.measure("criticality") if m else _null_context()):
            c = self.criticality_agent.run(raw_readings, tinyml_output)
        print(
            f"[Agent 5 - Criticality] {'!!' if c.critical else 'OK'} "
            f"Scenario: {c.scenario} | Severity: {c.severity}"
        )

        context: PipelineContext = {
            "sensor_id": sensor_id,
            "trust_score": trust_score,
            "trust_level": trust_level,
            "sanity_score": s.sanity_score,
            "failed_fields": s.failed_fields,
            "critical": c.critical,
            "scenario": c.scenario,
            "severity": c.severity,
            "tinyml_recommendation": tinyml_output.get("recommended_action"),
            "policy_allowed": tinyml_output.get("recommended_action")
            in ACTION_WHITELIST,
        }

        with (m.measure("decision") if m else _null_context()):
            d = self.decision_agent.run(context)

        decision_source = getattr(d, "source", "llm")
        print(
            f"[Agent 6 - Decision]   -> {d.decision} | Action: {d.action_required}"
            f" | source: {decision_source}"
        )

        # ── Enforcement Layer ─────────────────────────────
        result = self.action_handler.route(
            d.action_required,
            d.to_dict(),
            trust_level,
            context={**context, "raw_readings": raw_readings},
        )

        # ── Logging & Metrics ─────────────────────────────
        pipeline_latency_ms = round((perf_counter() - start_time) * 1000, 2)
        self.logger.log(
            sensor_id=sensor_id,
            trust_score=trust_score,
            trust_level=trust_level,
            decision=d.to_dict(),
            result=result,
            scenario=c.scenario,
            critical=c.critical,
            additional={
                "pipeline_latency_ms": pipeline_latency_ms,
                "decision_source": decision_source,
            },
        )

        if m is not None:
            m.record_reading(
                trust_score=trust_score,
                scenario=c.scenario,
                decision=d.decision,
                action=d.action_required,
                result=result,
                source=decision_source,
            )
            self._sync_support_metrics()

        return result

    @property
    def cache_stats(self) -> dict | None:
        """Return decision cache statistics, or None if no cache is attached."""
        if self._cache is None:
            return None
        return self._cache.stats

    # ── private helpers ──────────────────────────────────

    def _get_trust_level(self, score: float) -> TrustLevel:
        if score >= TRUST_LEVEL_THRESHOLDS["HIGH"]:
            return TrustLevel.HIGH
        if score >= TRUST_LEVEL_THRESHOLDS["MEDIUM"]:
            return TrustLevel.MEDIUM
        return TrustLevel.LOW

    def _reject(
        self,
        sensor_id: str,
        reason: str,
        score: float,
        start_time: float,
    ) -> str:
        result = self.action_handler.reject_and_alert(
            reason, {"sensor_id": sensor_id}
        )
        pipeline_latency_ms = round((perf_counter() - start_time) * 1000, 2)
        self.logger.log(
            sensor_id=sensor_id,
            trust_score=score,
            trust_level=TrustLevel.LOW,
            decision={"reasoning": reason, "decision": "reject", "action_required": "cloud"},
            result=result,
            scenario="N/A",
            critical=False,
            additional={"pipeline_latency_ms": pipeline_latency_ms},
        )
        if self.metrics is not None:
            self.metrics.record_reading(
                trust_score=score,
                scenario="N/A",
                decision="reject",
                action="cloud",
                result=result,
                source="rule",
            )
            self._sync_support_metrics()
        return result

    def _sync_support_metrics(self) -> None:
        """Synchronize absolute cache and connectivity counters."""
        if self.metrics is None:
            return
        if self._cache is not None:
            stats = self._cache.stats
            self.metrics.set_cache_stats(
                hits=stats["hits"],
                misses=stats["misses"],
            )
        connectivity = connectivity_stats()
        self.metrics.set_degraded_activations(
            connectivity.get("degraded_mode_activations", 0)
        )


@contextmanager
def _null_context() -> Iterator[None]:
    """A no-op context manager used when no metrics collector is attached."""
    yield
