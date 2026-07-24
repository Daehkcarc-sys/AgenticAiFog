from __future__ import annotations

import json
import sqlite3

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
from context.multimodal_fusion import MultimodalFusionAgent
from cloud_events import TOPICS, envelope, topic_for_event, validate_event
from cloud_storage import CloudEventStore, DigitalTwinStore
from cloud_sync import CloudPublisher, LocalQueuePublisher, ModelUpdateStore, ReliableCloudPublisher
from decision_cache import DecisionCache
from logger import FogLogger
from models import TrustLevel
from pipeline import FogPipeline
from support_services import CloudSyncStore, LocalRuleStore, SecurityAccessControl
from tools.backup_sqlite import backup_file
from tools.retention import prune_cloud, prune_twin
from tools.governance_consumer import apply_governance_event
from digital_twin.calibration import fit_soil_water_parameters, load_calibration_profile, save_calibration_profile
from digital_twin.contracts import FogSummaryContract, validate_fog_summary_payload
from digital_twin.feedback import HumanFeedback, MODEL_UPDATE_SCHEMA, POLICY_UPDATE_SCHEMA
from digital_twin.feedback_store import FeedbackStore
from digital_twin.connectivity import twin_command_event, twin_state_event, validate_twin_connectivity_event
from digital_twin.optimization import IrrigationOptimizer
from digital_twin.repositories import SQLiteRepositories, build_repositories
from digital_twin.simulator import DigitalTwinEngine
from services.digital_twin_service import DigitalTwinService
from tools.dashboard import DashboardHandler
from digital_twin.synthetic_events import RARE_EVENT_SCHEMA, generate_rare_event_dataset


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


    def test_multimodal_fusion_placeholder_accepts_visual_features(self) -> None:
        result = MultimodalFusionAgent().run(
            {
                "source": "drone",
                "ndvi": 0.28,
                "canopy_temperature": 37.5,
                "thermal_anomaly": 0.8,
            }
        )
        self.assertTrue(result.available)
        self.assertIn("drone", result.sources)
        self.assertIn("low vegetation index", result.risk_indicators)
        self.assertIn("image ingestion", " ".join(result.limitations))

    def test_pipeline_logs_explanation_trace_and_multimodal_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "decisions.json"
            pipeline = FogPipeline()
            pipeline.logger = FogLogger(log_path)
            message = self._fresh_message()
            message["multimodal_inputs"] = {
                "source": "satellite",
                "ndvi": 0.3,
                "water_stress_index": 0.8,
            }

            result = pipeline.run(message)
            self.assertTrue(result.endswith("queued") or result.endswith("executed"))

            logs = json.loads(log_path.read_text(encoding="utf-8"))
            trace = logs[-1]["explanation_trace"]
            layer_names = [layer["layer"] for layer in trace["layers"]]
            self.assertEqual(
                layer_names,
                [
                    "trust",
                    "sanity",
                    "context",
                    "anomaly",
                    "multimodal_fusion",
                    "criticality",
                    "decision",
                    "enforcement",
                ],
            )
            self.assertTrue(logs[-1]["multimodal_fusion"]["available"])
            self.assertIn("visual water stress", logs[-1]["multimodal_fusion"]["risk_indicators"])

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



    def test_cloud_storage_and_digital_twin_persist_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            event = envelope(
                "fog_summary",
                {
                    "sensor_id": "SENSOR_001",
                    "zone_id": "zone-1",
                    "scenario": "Water deficit",
                    "severity": "medium",
                    "critical": False,
                    "decision": "validate",
                    "result": "cloud_decided: manual_review",
                    "trust_score": 0.91,
                    "context_summary": "soil moisture falling",
                    "multimodal_summary": "visual water stress",
                },
            )
            cloud_store = CloudEventStore(Path(tmp) / "cloud.db")
            twin_store = DigitalTwinStore(Path(tmp) / "twin.db")

            cloud_store.insert_event("sensor-data", event)
            twin_store.apply_event("sensor-data", event)

            self.assertEqual(cloud_store.summary()["total_events"], 1)
            self.assertEqual(cloud_store.latest_events()[0]["scenario"], "Water deficit")
            zones = twin_store.zones()
            self.assertEqual(zones[0]["zone_id"], "zone-1")
            self.assertEqual(zones[0]["scenario"], "Water deficit")

    def test_cloud_event_envelope_and_topic_routing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            publisher = LocalQueuePublisher(path)
            status = publisher.publish(
                "sensor-data",
                {
                    "event_id": "evt-1",
                    "event_type": "fog_summary",
                    "schema_version": "1.0",
                    "source": "fog-node",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "payload": {"sensor_id": "SENSOR_001"},
                },
            )
            self.assertEqual(status, "queued_local")
            event = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            validate_event(event["payload"])
            self.assertEqual(topic_for_event("fog_summary", {"critical": True}), "critical-events")
            self.assertEqual(topic_for_event("trust_event", {}), "trust-events")

    def test_reliable_cloud_publisher_dead_letters_failures(self) -> None:
        class FailingPublisher(CloudPublisher):
            def publish(self, topic: str, payload: dict) -> str:
                raise RuntimeError("broker down")

        with tempfile.TemporaryDirectory() as tmp:
            dead_letter = LocalQueuePublisher(Path(tmp) / "dead.jsonl")
            publisher = ReliableCloudPublisher(
                FailingPublisher(),
                retries=1,
                backoff_seconds=0,
                dead_letter=dead_letter,
            )
            status = publisher.publish(
                "sensor-data",
                {
                    "event_id": "evt-1",
                    "event_type": "fog_summary",
                    "schema_version": "1.0",
                    "source": "fog-node",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "payload": {"sensor_id": "SENSOR_001"},
                },
            )
            self.assertEqual(status, "queued_dead_letter")
            dead = json.loads((Path(tmp) / "dead.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(dead["topic"], "fog-dead-letter")
            self.assertEqual(dead["payload"]["event_type"], "dead_letter")

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

    def test_twin_connectivity_events_are_routed_and_validated(self) -> None:
        state_event = twin_state_event("farm-1", "twin-zone-1", {"risk_index": 0.7})
        command_event = twin_command_event("twin-zone-1", "sync_now")

        validate_twin_connectivity_event(state_event)
        validate_twin_connectivity_event(command_event)
        self.assertEqual(topic_for_event("twin_state", state_event["payload"]), TOPICS["twin_state"])
        self.assertEqual(topic_for_event("twin_command", command_event["payload"]), TOPICS["twin_command"])

    def test_irrigation_optimizer_prioritizes_dry_zone(self) -> None:
        recommendations = IrrigationOptimizer().recommend(
            [
                {"zone_id": "dry", "risk_index": 0.8, "soil": {"moisture": 18}},
                {"zone_id": "ok", "risk_index": 0.1, "soil": {"moisture": 50}},
            ]
        )

        self.assertEqual(recommendations[0].zone_id, "dry")
        self.assertEqual(recommendations[0].action, "irrigate")

    def test_dashboard_health_uses_repository_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            DashboardHandler.repositories = build_repositories(
                db_backend="sqlite",
                cloud_db=Path(tmp) / "cloud.db",
                twin_db=Path(tmp) / "twin.db",
                feedback_path=Path(tmp) / "feedback.jsonl",
            )
            DashboardHandler.read_token = None
            DashboardHandler.write_token = None
            DashboardHandler.admin_token = None
            health = DashboardHandler._health(DashboardHandler)

            self.assertEqual(health["db_backend"], "sqlite")
            self.assertIn("topics", health)
            self.assertEqual(health["repository"]["cloud"]["total_events"], 0)
    def test_repository_factory_defaults_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repos = build_repositories(
                db_backend="sqlite",
                cloud_db=Path(tmp) / "cloud.db",
                twin_db=Path(tmp) / "twin.db",
                feedback_path=Path(tmp) / "feedback.jsonl",
            )

            self.assertIsInstance(repos, SQLiteRepositories)
            self.assertEqual(repos.cloud_events.summary()["total_events"], 0)

    def test_postgres_schema_documents_production_tables(self) -> None:
        schema = Path("db/postgres_schema.sql").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS fog_events", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS zone_state", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS calibration_profiles", schema)
        self.assertIn("CREATE TABLE IF NOT EXISTS human_feedback", schema)

    def test_digital_twin_service_applies_event_and_steps_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = DigitalTwinService(farm_id="farm-1", db_backend="sqlite", simulation_step_minutes=30)
            service.repositories = build_repositories(
                db_backend="sqlite",
                cloud_db=Path(tmp) / "cloud.db",
                twin_db=Path(tmp) / "twin.db",
                feedback_path=Path(tmp) / "feedback.jsonl",
            )
            event = envelope(
                "fog_summary",
                {
                    "sensor_id": "SENSOR_001",
                    "zone_id": "zone-1",
                    "scenario": "Water deficit",
                    "severity": "medium",
                    "raw_readings": {"soil_moisture": 22},
                },
            )

            applied = service.apply_event("sensor-data", event)
            stepped = service.step(weather={"temperature": 34, "humidity": 30, "rainfall": 0})

            self.assertEqual(applied["status"], "applied")
            self.assertEqual(stepped["status"], "simulated")
            self.assertIn("zone-1", stepped["zones"])
    def test_digital_twin_contract_normalizes_fog_summary(self) -> None:
        payload = {
            "sensor_id": "SENSOR_001",
            "zone": "north-field",
            "scenario": "Water deficit",
            "severity": "medium",
            "critical": False,
            "trust_score": 0.88,
            "raw_readings": {"soil_moisture": 18, "ph": 6.7},
        }
        validate_fog_summary_payload(payload)
        summary = FogSummaryContract.from_payload(payload)

        self.assertEqual(summary.zone_id, "north-field")
        self.assertEqual(summary.sensor_id, "SENSOR_001")
        self.assertEqual(summary.raw_readings["soil_moisture"], 18)

    def test_digital_twin_engine_updates_state_and_runs_what_if(self) -> None:
        engine = DigitalTwinEngine("farm-1")
        engine.apply_fog_summary(
            {
                "sensor_id": "SENSOR_001",
                "zone_id": "zone-1",
                "scenario": "Water deficit",
                "severity": "high",
                "critical": True,
                "decision": "irrigate",
                "decision_source": "rule",
                "confidence": 0.91,
                "trust_score": 0.93,
                "raw_readings": {"soil_moisture": 14, "ph": 6.4, "salinity": 1.1},
            },
            event_id="evt-twin-1",
        )

        state = engine.dashboard_state()
        self.assertEqual(state["event_count"], 1)
        self.assertEqual(state["zones"][0]["zone_id"], "zone-1")
        self.assertEqual(state["zones"][0]["soil"]["moisture"], 14.0)
        result = engine.what_if("zone-1", "irrigation", "irrigate")
        self.assertIn(result.recommendation, {"irrigate", "monitor_after_irrigation"})
        self.assertLess(result.projected_risk, result.baseline_risk)

    def test_digital_twin_calibration_profile_fits_and_persists(self) -> None:
        profile = fit_soil_water_parameters(
            [
                {"before_moisture": 20.0, "after_moisture": 31.0, "minutes": 60, "irrigated": True},
                {"before_moisture": 30.0, "after_moisture": 34.0, "minutes": 60, "rainfall": 20.0},
                {"before_moisture": 45.0, "after_moisture": 42.0, "minutes": 60, "temperature": 38.0, "humidity": 30.0},
            ],
            farm_id="farm-1",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.json"
            save_calibration_profile(profile, path)
            loaded = load_calibration_profile(path)

        self.assertEqual(loaded.farm_id, "farm-1")
        self.assertGreater(loaded.soil_water.irrigation_gain, 1.0)
        self.assertEqual(loaded.metrics["records_used"], 3)

    def test_digital_twin_uses_calibrated_soil_parameters(self) -> None:
        profile = fit_soil_water_parameters(
            [{"before_moisture": 20.0, "after_moisture": 35.0, "minutes": 60, "irrigated": True}],
            farm_id="farm-1",
        )
        engine = DigitalTwinEngine("farm-1", calibration=profile)
        engine.apply_fog_summary(
            {"sensor_id": "SENSOR_001", "zone_id": "zone-1", "raw_readings": {"soil_moisture": 20.0}},
            created_at="2026-01-01T00:00:00+00:00",
        )
        result = engine.step(minutes=60, interventions={"zone-1": "irrigate"})

        self.assertGreaterEqual(result.zones["zone-1"]["soil_moisture"], 34.0)
        self.assertEqual(engine.dashboard_state()["calibration"]["source"], "fit_soil_water_parameters")


    def test_digital_twin_state_evolves_over_time(self) -> None:
        engine = DigitalTwinEngine("farm-1")
        engine.apply_fog_summary(
            {
                "sensor_id": "SENSOR_001",
                "zone_id": "zone-1",
                "scenario": "Normal",
                "severity": "low",
                "critical": False,
                "trust_score": 0.95,
                "raw_readings": {"soil_moisture": 40, "ph": 6.5, "salinity": 1.0},
            },
            created_at="2026-01-01T00:00:00+00:00",
        )

        first = engine.step(minutes=60, weather={"temperature": 40, "humidity": 20, "rainfall": 0})
        second = engine.step(minutes=60, weather={"temperature": 40, "humidity": 20, "rainfall": 0})
        state = engine.dashboard_state()["zones"][0]

        self.assertEqual(first.step, 1)
        self.assertEqual(second.step, 2)
        self.assertLess(state["soil"]["moisture"], 40.0)
        self.assertGreaterEqual(state["history_length"], 3)
        self.assertIn("soil_water_balance_v1", engine.dashboard_state()["process_models"])

    def test_digital_twin_accepts_pluggable_process_model(self) -> None:
        class CustomModel:
            name = "custom_model"

            def step(self, zone, context):
                zone.dynamic_state["custom_called"] = zone.dynamic_state.get("custom_called", 0) + 1
                return {"model": self.name, "called": zone.dynamic_state["custom_called"]}

        engine = DigitalTwinEngine("farm-1", process_models=[CustomModel()])
        engine.apply_fog_summary({"sensor_id": "SENSOR_001", "zone_id": "zone-1"})
        result = engine.step(minutes=5)

        self.assertEqual(result.zones["zone-1"]["dynamic_state"]["custom_called"], 1)
        self.assertEqual(engine.dashboard_state()["process_models"], ["custom_model"])


    def test_rare_event_dataset_has_documented_ml_schema(self) -> None:
        rows = generate_rare_event_dataset(seed=3, repeats_per_scenario=1)
        labels = {row["target"] for row in rows}

        self.assertIn("schema_version", RARE_EVENT_SCHEMA)
        self.assertIn("features", RARE_EVENT_SCHEMA)
        self.assertIn("Water deficit", labels)
        self.assertIn("Equipment failure", labels)
        self.assertIn("features", rows[0])
        self.assertIn("tinyml_confidence", rows[0]["features"])

    def test_human_feedback_and_update_paths_are_specified(self) -> None:
        feedback = HumanFeedback(
            event_id="evt-1",
            zone_id="zone-1",
            reviewer_id="supervisor-a",
            label="Crop disease risk",
            corrected_action="manual_review",
        )
        label = feedback.to_training_label()

        self.assertEqual(label["source"], "dashboard_human_feedback")
        self.assertEqual(label["target"], "Crop disease risk")
        self.assertEqual(POLICY_UPDATE_SCHEMA["topic"], "policy-updates")
        self.assertEqual(MODEL_UPDATE_SCHEMA["topic"], "model-updates")

    def test_feedback_store_exports_training_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FeedbackStore(Path(tmp) / "feedback.jsonl")
            store.append(
                HumanFeedback(
                    event_id="evt-1",
                    zone_id="zone-1",
                    reviewer_id="reviewer-a",
                    label="Water deficit",
                    corrected_action="irrigate",
                )
            )
            manifest = store.export_training_labels(Path(tmp) / "labels.jsonl")

            self.assertEqual(manifest["records"], 1)
            exported = json.loads((Path(tmp) / "labels.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(exported["target"], "Water deficit")
            self.assertEqual(exported["source"], "dashboard_human_feedback")

    def test_governance_consumer_applies_policy_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = apply_governance_event(
                {
                    "event_id": "policy-1",
                    "event_type": "policy_update",
                    "schema_version": "1.0",
                    "source": "cloud-governance",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "payload": {"rules": {"high_trust": "allow_whitelisted_local_action"}},
                },
                rule_store=LocalRuleStore(Path(tmp) / "rules.json"),
                model_store=ModelUpdateStore(Path(tmp) / "models.json"),
            )

            self.assertEqual(result["event_type"], "policy_update")
            self.assertEqual(result["status"], "applied")
            self.assertEqual(result["policy"]["version"], 2)


    def test_backup_sqlite_copies_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "cloud.db"
            source.write_bytes(b"sqlite-data")
            target = backup_file(source, Path(tmp) / "backups")

            self.assertIsNotNone(target)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_bytes(), b"sqlite-data")

    def test_retention_prunes_cloud_and_twin_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cloud_db = Path(tmp) / "cloud.db"
            twin_db = Path(tmp) / "twin.db"
            CloudEventStore(cloud_db)
            DigitalTwinStore(twin_db)

            conn = sqlite3.connect(cloud_db)
            try:
                conn.execute(
                    """
                    INSERT INTO cloud_events (
                        event_id, topic, event_type, schema_version, source,
                        created_at, payload_json, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("old-cloud", "sensor-data", "fog_summary", "1.0", "test", "old", "{}", "2000-01-01T00:00:00+00:00"),
                )
                conn.execute(
                    """
                    INSERT INTO cloud_events (
                        event_id, topic, event_type, schema_version, source,
                        created_at, payload_json, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("new-cloud", "sensor-data", "fog_summary", "1.0", "test", "new", "{}", "2099-01-01T00:00:00+00:00"),
                )
                conn.commit()
            finally:
                conn.close()

            conn = sqlite3.connect(twin_db)
            try:
                conn.execute(
                    """
                    INSERT INTO twin_events (event_id, topic, zone_id, sensor_id, event_json, applied_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("old-twin", "sensor-data", "zone-1", "SENSOR_001", "{}", "2000-01-01T00:00:00+00:00"),
                )
                conn.execute(
                    """
                    INSERT INTO twin_events (event_id, topic, zone_id, sensor_id, event_json, applied_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("new-twin", "sensor-data", "zone-1", "SENSOR_001", "{}", "2099-01-01T00:00:00+00:00"),
                )
                conn.commit()
            finally:
                conn.close()

            self.assertEqual(prune_cloud(cloud_db, "2026-01-01T00:00:00+00:00"), 1)
            self.assertEqual(prune_twin(twin_db, "2026-01-01T00:00:00+00:00"), 1)

            conn = sqlite3.connect(cloud_db)
            try:
                self.assertEqual(conn.execute("SELECT event_id FROM cloud_events").fetchone()[0], "new-cloud")
            finally:
                conn.close()

            conn = sqlite3.connect(twin_db)
            try:
                self.assertEqual(conn.execute("SELECT event_id FROM twin_events").fetchone()[0], "new-twin")
            finally:
                conn.close()

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





















