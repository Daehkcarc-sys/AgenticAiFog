from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from action_handler import ActionHandler
from agents.criticality_agent import CriticalityAgent
from agents.decision_agent import DecisionAgent
from agents.timestamp_agent import TimestampAgent
from decision_cache import DecisionCache
from llm_factory import (
    reset_connectivity_state,
    safe_invoke,
    set_offline_mode,
)
from logger import FogLogger
from main import load_dataset
from metrics import PipelineMetrics
from models import CriticalityScenario, TrustLevel
from pipeline import FogPipeline


def normal_readings() -> dict:
    return {
        "soil_moisture": 55.0,
        "temperature": 25.0,
        "humidity": 60.0,
        "rainfall": 0.0,
        "ph": 6.5,
        "nitrogen": 80.0,
        "phosphorus": 40.0,
        "potassium": 40.0,
    }


def decision_context(**overrides) -> dict:
    context = {
        "sensor_id": "SENSOR_001",
        "trust_score": 0.95,
        "trust_level": TrustLevel.HIGH,
        "sanity_score": 1.0,
        "failed_fields": [],
        "critical": False,
        "scenario": CriticalityScenario.NORMAL.value,
        "severity": "low",
        "tinyml_recommendation": "no_action",
        "policy_allowed": True,
    }
    context.update(overrides)
    return context


class FakeCloud:
    def __init__(self) -> None:
        self.escalations = 0
        self.rejections = 0

    def escalate(self, context: dict) -> dict:
        self.escalations += 1
        return {"cloud_decision": "manual_review"}

    def notify_rejection(self, sensor_id: str, reason: str) -> None:
        self.rejections += 1


class P0StabilizationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_connectivity_state()
        set_offline_mode(True)

    def tearDown(self) -> None:
        set_offline_mode(False)
        reset_connectivity_state()

    def test_offline_mode_never_opens_network_socket(self) -> None:
        fallback = {"decision": "escalate"}
        with patch("llm_factory.socket.create_connection") as probe:
            result = safe_invoke("system", "user", fallback)
        self.assertEqual(result["decision"], fallback["decision"])
        self.assertTrue(result["_fallback_used"])
        self.assertEqual(result["_fallback_reason"], "offline_mode")
        probe.assert_not_called()

    def test_bundled_zip_dataset_loads_without_extraction(self) -> None:
        dataset = load_dataset()
        self.assertEqual(len(dataset), 2200)
        self.assertIn("soil_moisture", dataset.columns)

    def test_timestamp_accepts_aware_offset_and_zulu(self) -> None:
        agent = TimestampAgent()
        offset_now = datetime.now(timezone(timedelta(hours=2))).isoformat()
        zulu_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.assertTrue(agent.run({"timestamp": offset_now}).passed)
        self.assertTrue(agent.run({"timestamp": zulu_now}).passed)

    def test_timestamp_rejects_future_and_stale_readings(self) -> None:
        agent = TimestampAgent()
        future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        stale = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        self.assertFalse(agent.run({"timestamp": future}).passed)
        self.assertFalse(agent.run({"timestamp": stale}).passed)

    def test_normal_gate_uses_crop_operating_ranges(self) -> None:
        agent = CriticalityAgent()
        tinyml = {"confidence": 0.95, "recommended_action": "no_action"}
        normal = agent.run(normal_readings(), tinyml)
        hot = agent.run({**normal_readings(), "temperature": 55.0}, tinyml)
        drought = agent.run({**normal_readings(), "soil_moisture": 10.0}, tinyml)

        self.assertFalse(normal.critical)
        self.assertEqual(normal.scenario, CriticalityScenario.NORMAL.value)
        self.assertTrue(hot.critical)
        self.assertEqual(hot.scenario, CriticalityScenario.HEAT_STRESS.value)
        self.assertTrue(drought.critical)
        self.assertEqual(drought.scenario, CriticalityScenario.WATER_DEFICIT.value)

    def test_high_trust_rule_requires_all_safety_gates(self) -> None:
        agent = DecisionAgent()
        safe = agent.run(decision_context())
        critical = agent.run(decision_context(critical=True))
        bad_sanity = agent.run(decision_context(sanity_score=0.75))
        blocked_policy = agent.run(decision_context(policy_allowed=False))

        self.assertEqual(safe.decision, "act_locally")
        self.assertEqual(critical.source, "fallback")
        self.assertNotEqual(critical.decision, "act_locally")
        self.assertNotEqual(bad_sanity.decision, "act_locally")
        self.assertNotEqual(blocked_policy.decision, "act_locally")

    def test_enforcement_rechecks_critical_context(self) -> None:
        cloud = FakeCloud()
        handler = ActionHandler(cloud=cloud)
        result = handler.route(
            "irrigate",
            {"action_required": "irrigate"},
            TrustLevel.HIGH,
            context=decision_context(critical=True),
        )
        self.assertEqual(result, "cloud_decided: manual_review")
        self.assertEqual(cloud.escalations, 1)

    def test_metric_synchronization_does_not_inflate_counts(self) -> None:
        metrics = PipelineMetrics()
        metrics.set_cache_stats(hits=0, misses=1)
        metrics.set_cache_stats(hits=0, misses=2)
        metrics.set_degraded_activations(1)
        metrics.set_degraded_activations(1)
        report = metrics.to_dict()
        self.assertEqual(report["cache"]["misses"], 2)
        self.assertEqual(report["degraded_mode_activations"], 1)

    def test_offline_pipeline_runs_and_counts_early_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics = PipelineMetrics()
            pipeline = FogPipeline(metrics=metrics, cache=DecisionCache())
            pipeline.logger = FogLogger(Path(temp_dir) / "decisions.json")

            normal_message = {
                "sensor_id": "SENSOR_001",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "raw_readings": normal_readings(),
                "tinyml_output": {
                    "recommended_action": "no_action",
                    "confidence": 0.95,
                    "anomaly_detected": False,
                },
            }
            self.assertEqual(pipeline.run(normal_message), "no_action_executed")

            rejected_message = {**normal_message, "sensor_id": "UNKNOWN_999"}
            self.assertTrue(pipeline.run(rejected_message).startswith("rejected:"))

            report = metrics.to_dict()
            self.assertEqual(report["total_readings"], 2)
            self.assertEqual(report["decision_distribution"]["reject"], 1)


if __name__ == "__main__":
    unittest.main()
