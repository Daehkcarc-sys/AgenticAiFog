from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

from action_handler import ActionHandler
from anomaly_detector import MultiLevelAnomalyDetector
from agents import (
    ContextManagerAgent,
    CriticalityAgent,
    DataValidationAgent,
    DecisionAgent,
    TimestampAgent,
    TrustScoreAgent,
    ValueSanityAgent,
)
from config import ACTION_WHITELIST, TRUST_LEVEL_THRESHOLDS
from context.multimodal_fusion import MultimodalFusionAgent
from contracts import PipelineContext
from decision_cache import DecisionCache
from llm_factory import connectivity_stats
from logger import FogLogger
from metrics import PipelineMetrics
from models import TrustLevel
from support_services import (
    CloudSyncStore,
    ConnectivityManager,
    LocalRuleStore,
    ResourceMonitor,
    SecurityAccessControl,
)


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
        self.context_manager = ContextManagerAgent()
        self.anomaly_detector = MultiLevelAnomalyDetector()
        self.multimodal_fusion = MultimodalFusionAgent()
        self.criticality_agent = CriticalityAgent()
        self.decision_agent = DecisionAgent(cache=cache)
        self.action_handler = ActionHandler()
        self.logger = FogLogger()
        self.metrics = metrics
        self._cache = cache
        self.resource_monitor = ResourceMonitor()
        self.connectivity_manager = ConnectivityManager()
        self.local_rule_store = LocalRuleStore()
        self.security = SecurityAccessControl()
        self.cloud_sync = CloudSyncStore()

    def run(self, sensor_data: dict) -> str:
        sensor_id = sensor_data.get("sensor_id")
        raw_readings = sensor_data.get("raw_readings", {})
        tinyml_output = sensor_data.get("tinyml_output", {})

        m = self.metrics
        start_time = perf_counter()

        # â”€â”€ Trust Layer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        with (m.measure("data_validation") if m else _null_context()):
            v = self.data_validator.run(sensor_data)
        print(f"[Agent 1 - Validation] {'PASS' if v.passed else 'FAIL'} {v.reason}")
        if not v.passed:
            return self._reject(sensor_id, v.reason, 0.0, start_time)
        security_context = self.security.audit_context(sensor_id, sensor_data=sensor_data)
        self.security.append_audit(
            {
                "sensor_id": sensor_id,
                "event": "data_validation_passed",
                "security": security_context,
            }
        )
        if security_context.get("signature_valid") is False:
            return self._reject(sensor_id, "Invalid sensor signature", 0.0, start_time)

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

        # â”€â”€ Context Layer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        with (m.measure("context") if m else _null_context()):
            ctx = self.context_manager.run(sensor_id, raw_readings, tinyml_output)
        print(
            f"[Context]              History: {ctx.history_count} readings"
            f" | Trends: {len(ctx.trends)} fields"
        )

        with (m.measure("anomaly_detection") if m else _null_context()):
            anomaly_report = self.anomaly_detector.run(
                raw_readings=raw_readings,
                history=self.context_manager.history_for_sensor(sensor_id),
                context=ctx.to_dict(),
            )
        print(
            f"[Agent 2 - Anomaly]    Severity: {anomaly_report.severity} "
            f"| Score: {anomaly_report.score}"
        )

        with (m.measure("multimodal_fusion") if m else _null_context()):
            multimodal = self.multimodal_fusion.run(
                sensor_data.get("multimodal_inputs")
                or sensor_data.get("multimodal_context")
                or sensor_data.get("visual_features")
            )
        print(f"[Multimodal]          {multimodal.semantic_summary}")

        resource_snapshot = self.resource_monitor.snapshot()
        connectivity_status = self.connectivity_manager.status()
        context_payload = {
            **ctx.to_dict(),
            "multi_level_anomalies": anomaly_report.to_dict(),
            "multimodal_fusion": multimodal.to_dict(),
        }

        # Merge zone-level context when provided by ZoneFogPipeline (item 3).
        zone_context = sensor_data.get("zone_context")
        if zone_context:
            context_payload["zone_context"] = zone_context
            zone_findings = zone_context.get("anomaly_findings", [])
            if zone_findings:
                context_payload.setdefault("zone_anomaly_findings", zone_findings)

        # â”€â”€ Intelligence Layer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        with (m.measure("criticality") if m else _null_context()):
            c = self.criticality_agent.run(
                raw_readings,
                tinyml_output,
                context_payload,
            )
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
            # Context Layer enrichment
            "context": context_payload,
            "semantic_context": ctx.semantic_context,
            "rolling_averages": ctx.rolling_averages,
            "trends": ctx.trends,
            "derived_features": ctx.derived_features,
            "anomaly_indicators": ctx.anomaly_indicators,
            "multi_level_anomalies": anomaly_report.to_dict(),
            "multimodal_fusion": multimodal.to_dict(),
            "resource_snapshot": resource_snapshot.to_dict(),
            "connectivity": connectivity_status,
            "local_rules": self.local_rule_store.to_dict(),
            "security": security_context,
            # Link state from TelemetryRecord (item 4) — used by DecisionAgent
            # for NTN-aware routing (item 5).
            "link_state": sensor_data.get("link_state", "terrestrial"),
            "zone_id": sensor_data.get("zone_id"),
        }

        with (m.measure("decision") if m else _null_context()):
            d = self.decision_agent.run(context)

        decision_source = getattr(d, "source", "llm")
        print(
            f"[Agent 6 - Decision]   -> {d.decision} | Action: {d.action_required}"
            f" | source: {decision_source}"
        )

        # â”€â”€ Enforcement Layer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        result = self.action_handler.route(
            d.action_required,
            d.to_dict(),
            trust_level,
            context={**context, "raw_readings": raw_readings},
        )
        security_context["action_authorized"] = self.security.authorize_action(
            d.action_required
        )

        explanation_trace = self._build_explanation_trace(
            validation_reason=v.reason,
            timestamp_reason=t.reason,
            trust_score=trust_score,
            trust_level=trust_level,
            sanity_score=s.sanity_score,
            failed_fields=s.failed_fields,
            semantic_context=ctx.semantic_context,
            anomaly_report=anomaly_report.to_dict(),
            multimodal=multimodal.to_dict(),
            criticality=c.to_dict(),
            decision=d.to_dict(),
            decision_source=decision_source,
            enforcement_result=result,
        )

        sync_summary = {
            "sensor_id": sensor_id,
            "trust_score": trust_score,
            "scenario": c.scenario,
            "decision": d.decision,
            "result": result,
            "context_summary": ctx.semantic_context,
            "anomaly_severity": anomaly_report.severity,
            "connectivity": connectivity_status,
            "multimodal_summary": multimodal.semantic_summary,
            "explanation_trace": explanation_trace,
        }
        self.cloud_sync.enqueue_summary(sync_summary)
        if not connectivity_status.get("offline_mode"):
            for queued_summary in self.cloud_sync.drain():
                self.action_handler.cloud.upload_summary(queued_summary)
            self.connectivity_manager.mark_cloud_success()

        # â”€â”€ Logging & Metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                "context_history_count": ctx.history_count,
                "context_semantic": ctx.semantic_context,
                "context_anomalies": ctx.anomaly_indicators,
                "multi_level_anomalies": anomaly_report.to_dict(),
                "multimodal_fusion": multimodal.to_dict(),
                "explanation_trace": explanation_trace,
                "resource_snapshot": resource_snapshot.to_dict(),
                "connectivity": connectivity_status,
                "security": security_context,
                "cloud_sync_pending": self.cloud_sync.pending_count(),
                "cloud_sync_status": self.action_handler.cloud.sync_status(),
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

    # â”€â”€ private helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        self.security.append_audit(
            {"sensor_id": sensor_id, "event": "rejected", "reason": reason}
        )
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


    @staticmethod
    def _build_explanation_trace(
        validation_reason: str,
        timestamp_reason: str,
        trust_score: float,
        trust_level: TrustLevel,
        sanity_score: float,
        failed_fields: list[str],
        semantic_context: str,
        anomaly_report: dict,
        multimodal: dict,
        criticality: dict,
        decision: dict,
        decision_source: str,
        enforcement_result: str,
    ) -> dict:
        """Create a readable layer-by-layer trace for audit and handover."""
        layers = [
            {
                "layer": "trust",
                "summary": (
                    f"validation passed; {timestamp_reason}; trust={trust_score:.2f} "
                    f"({trust_level.value if hasattr(trust_level, 'value') else trust_level})"
                ),
            },
            {
                "layer": "sanity",
                "summary": (
                    f"sanity={sanity_score:.2f}; failed_fields="
                    f"{failed_fields if failed_fields else 'none'}"
                ),
            },
            {
                "layer": "context",
                "summary": semantic_context,
            },
            {
                "layer": "anomaly",
                "summary": (
                    f"severity={anomaly_report.get('severity')}; "
                    f"score={anomaly_report.get('score')}"
                ),
            },
            {
                "layer": "multimodal_fusion",
                "summary": multimodal.get("semantic_summary", "no multimodal context"),
                "available": multimodal.get("available", False),
                "limitations": multimodal.get("limitations", []),
            },
            {
                "layer": "criticality",
                "summary": (
                    f"scenario={criticality.get('scenario')}; "
                    f"severity={criticality.get('severity')}; "
                    f"critical={criticality.get('critical')}"
                ),
                "reasoning": criticality.get("reasoning"),
            },
            {
                "layer": "decision",
                "summary": (
                    f"source={decision_source}; decision={decision.get('decision')}; "
                    f"action={decision.get('action_required')}"
                ),
                "reasoning": decision.get("reasoning"),
            },
            {
                "layer": "enforcement",
                "summary": f"result={enforcement_result}",
            },
        ]
        return {
            "schema_version": "1.0",
            "summary": " -> ".join(layer["layer"] for layer in layers),
            "layers": layers,
        }

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


