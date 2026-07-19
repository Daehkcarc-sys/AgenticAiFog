from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from action_handler import ActionHandler
from actuator_adapters import LocalQueueActuator
from agents.criticality_agent import CriticalityAgent
from agents.context_manager_agent import ContextManagerAgent
from agents.data_validation_agent import DataValidationAgent
from anomaly_detector import MultiLevelAnomalyDetector
from cloud_sync import LocalQueuePublisher, ModelUpdateStore
from decision_cache import DecisionCache
from models import TrustLevel
from pipeline import FogPipeline
from support_services import CloudSyncStore, LocalRuleStore, SecurityAccessControl


class FogComponentTests(unittest.TestCase):
    def test_criticality_normal(self) -> None:
        result = CriticalityAgent().run(
            self._message()["raw_readings"],
            self._message()["tinyml_output"],
            context={},
        )
        self.assertEqual(result.scenario, "Normal")
        self.assertFalse(result.critical)

    def test_criticality_water_deficit(self) -> None:
        readings = {**self._message()["raw_readings"], "soil_moisture": 10, "rainfall": 0}
        result = CriticalityAgent().run(
            readings,
            {"recommended_action": "irrigate", "confidence": 0.9},
            context={"trends": {"soil_moisture": -3}},
        )
        self.assertEqual(result.scenario, "Water deficit")

    def test_criticality_flooding(self) -> None:
        readings = {**self._message()["raw_readings"], "soil_moisture": 88, "rainfall": 80}
        result = CriticalityAgent().run(
            readings,
            {"recommended_action": "stop_irrigation", "confidence": 0.9},
            context={"trends": {"soil_moisture": 3}},
        )
        self.assertEqual(result.scenario, "Flooding")

    def test_criticality_heat_stress(self) -> None:
        readings = {**self._message()["raw_readings"], "temperature": 39, "humidity": 20}
        result = CriticalityAgent().run(
            readings,
            self._message()["tinyml_output"],
            context={"derived_features": {"vapor_pressure_deficit_kpa": 2.5}},
        )
        self.assertEqual(result.scenario, "Fire or heat stress")

    def test_criticality_disease_risk(self) -> None:
        readings = {**self._message()["raw_readings"], "temperature": 26, "humidity": 90}
        result = CriticalityAgent().run(readings, self._message()["tinyml_output"], context={})
        self.assertEqual(result.scenario, "Crop disease risk")

    def test_criticality_soil_degradation(self) -> None:
        readings = {
            **self._message()["raw_readings"],
            "ph": 9,
            "nitrogen": 10,
            "phosphorus": 10,
            "potassium": 10,
        }
        result = CriticalityAgent().run(readings, self._message()["tinyml_output"], context={})
        self.assertEqual(result.scenario, "Soil degradation")

    def test_criticality_equipment_failure(self) -> None:
        readings = {**self._message()["raw_readings"], "temperature": 999}
        result = CriticalityAgent().run(readings, self._message()["tinyml_output"], context={})
        self.assertEqual(result.scenario, "Equipment failure")
        self.assertEqual(result.severity, "high")

    def test_criticality_ambiguous_local_result(self) -> None:
        readings = {**self._message()["raw_readings"], "soil_moisture": 35, "temperature": 36}
        result = CriticalityAgent().run(
            readings,
            {"recommended_action": "irrigate", "confidence": 0.8},
            context={},
        )
        self.assertIn("under ambiguity", result.reasoning)

    def test_pipeline_criticality_local_smoke(self) -> None:
        result = FogPipeline().run(self._fresh_message())
        self.assertIn("queued", result)

    def test_validation_accepts_optional_pressure(self) -> None:
        data = self._message()
        data["raw_readings"]["pressure"] = 1012
        result = DataValidationAgent().run(data)
        self.assertTrue(result.passed, result.reason)

    def test_context_tracks_optional_fields(self) -> None:
        agent = ContextManagerAgent()
        result = agent.run(
            "SENSOR_001",
            {**self._message()["raw_readings"], "pressure": 1000},
            self._message()["tinyml_output"],
        )
        self.assertIn("pressure", result.rolling_averages)

    def test_anomaly_detector_domain_findings(self) -> None:
        report = MultiLevelAnomalyDetector().run(
            raw_readings={
                **self._message()["raw_readings"],
                "soil_moisture": 10,
                "rainfall": 0,
                "temperature": 40,
                "humidity": 20,
                "ph": 9,
            },
            history=[],
            context={"derived_features": {"vapor_pressure_deficit_kpa": 2.2}},
        )
        self.assertEqual(report.severity, "high")
        self.assertGreaterEqual(len(report.domain), 3)

    def test_security_signature_and_audit_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            security = SecurityAccessControl(secret="secret", audit_path=audit_path)
            message = self._message()
            message["signature"] = security.sign_message(
                message["sensor_id"],
                message["timestamp"],
                message["raw_readings"],
            )
            self.assertTrue(security.verify_signature(message))
            security.append_audit({"event": "one"})
            security.append_audit({"event": "two"})
            self.assertTrue(security.verify_audit_chain())

    def test_local_rule_store_persists_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            store = LocalRuleStore(path)
            updated = store.update({"rules": {"high_trust": "execute"}})
            self.assertEqual(updated["version"], 2)
            self.assertEqual(LocalRuleStore(path).to_dict()["rules"]["high_trust"], "execute")

    def test_cloud_sync_store_drains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CloudSyncStore(Path(tmp) / "queue.json")
            store.enqueue_summary({"x": 1})
            self.assertEqual(store.pending_count(), 1)
            self.assertEqual(store.drain(), [{"x": 1}])
            self.assertEqual(store.pending_count(), 0)

    def test_decision_cache_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = DecisionCache(path=path)
            context = {
                "trust_score": 0.9,
                "trust_level": TrustLevel.HIGH,
                "scenario": "Normal",
                "severity": "low",
                "critical": False,
                "sanity_score": 1.0,
                "tinyml_recommendation": "irrigate",
            }
            cache.store(context, {"decision": "act_locally"})
            self.assertEqual(
                DecisionCache(path=path).lookup(context)["decision"],
                "act_locally",
            )

    def test_action_handler_queues_actuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actuator = LocalQueueActuator(Path(tmp) / "actuators.jsonl")
            handler = ActionHandler(actuator=actuator)
            result = handler.route(
                "irrigate",
                {"reasoning": "ok"},
                TrustLevel.HIGH,
                context={"sensor_id": "SENSOR_001"},
            )
            self.assertEqual(result, "irrigate_queued")

    def test_cloud_publisher_and_model_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            publisher = LocalQueuePublisher(Path(tmp) / "events.jsonl")
            self.assertEqual(publisher.publish("topic", {"x": 1}), "queued_local")

            model_path = Path(tmp) / "model.bin"
            model_path.write_bytes(b"model")
            checksum = hashlib.sha256(b"model").hexdigest()
            store = ModelUpdateStore(Path(tmp) / "manifest.json")
            installed = store.install_update(
                {
                    "version": "v1",
                    "source_path": str(model_path),
                    "checksum_sha256": checksum,
                }
            )
            self.assertTrue(installed["active"])
            self.assertEqual(store.status()["active_version"], "v1")

    @staticmethod
    def _message() -> dict:
        return {
            "sensor_id": "SENSOR_001",
            "timestamp": "2026-07-17T12:00:00+00:00",
            "raw_readings": {
                "soil_moisture": 45,
                "temperature": 25,
                "humidity": 60,
                "rainfall": 2,
                "ph": 6.8,
                "nitrogen": 50,
                "phosphorus": 40,
                "potassium": 45,
            },
            "tinyml_output": {
                "recommended_action": "irrigate",
                "confidence": 0.9,
                "anomaly_detected": False,
            },
        }

    @staticmethod
    def _fresh_message() -> dict:
        from datetime import datetime, timezone

        message = FogComponentTests._message()
        message["timestamp"] = datetime.now(timezone.utc).isoformat()
        return message


if __name__ == "__main__":
    unittest.main()
