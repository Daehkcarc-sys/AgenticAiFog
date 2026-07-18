from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from context.zone_state import ZoneContextManager
from models import CriticalityScenario
from simulation.baselines import Baseline, BaselineSimulator
from simulation.experiment_metrics import summarize_outcomes
from simulation.generator import (
    EventInjection,
    FaultInjection,
    SimulationConfig,
    SyntheticTelemetryGenerator,
)
from simulation.network_model import MarkovConnectivityModel
from simulation.telemetry_schema import LinkState, SensorFault, TelemetryRecord


class TelemetryContractTests(unittest.TestCase):
    def test_round_trip_preserves_event_fault_and_timezone(self) -> None:
        record = TelemetryRecord(
            event_id="event-1",
            device_id="device-1",
            zone_id="zone-1",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            sequence_number=4,
            readings={"soil_moisture": 12.0},
            event_label=CriticalityScenario.WATER_DEFICIT,
            sensor_fault_label=SensorFault.GRADUAL_DRIFT,
            link_state=LinkState.NTN,
        )
        restored = TelemetryRecord.from_dict(record.to_dict())
        self.assertEqual(restored, record)
        self.assertIs(restored.event_label, CriticalityScenario.WATER_DEFICIT)
        self.assertIs(restored.sensor_fault_label, SensorFault.GRADUAL_DRIFT)

    def test_naive_timestamp_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TelemetryRecord(
                "event-1",
                "device-1",
                "zone-1",
                datetime(2026, 1, 1),
                0,
                {},
            )


class SyntheticGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimulationConfig(
            zone_count=1,
            sensors_per_zone=2,
            duration_minutes=40,
            sample_interval_minutes=10,
            seed=13,
        )

    def test_generation_is_deterministic_and_has_exact_size(self) -> None:
        first = SyntheticTelemetryGenerator(
            self.config,
            connectivity=MarkovConnectivityModel(seed=4),
        ).generate()
        second = SyntheticTelemetryGenerator(
            self.config,
            connectivity=MarkovConnectivityModel(seed=4),
        ).generate()
        self.assertEqual(
            [record.to_dict() for record in first],
            [record.to_dict() for record in second],
        )
        self.assertEqual(len(first), self.config.steps * 2)

    def test_environmental_event_and_sensor_fault_coexist(self) -> None:
        records = SyntheticTelemetryGenerator(
            self.config,
            events=[
                EventInjection(
                    "zone-1", CriticalityScenario.WATER_DEFICIT, 1, 2
                )
            ],
            faults=[
                FaultInjection(
                    "zone-1-sensor-1",
                    SensorFault.GRADUAL_DRIFT,
                    1,
                    2,
                    "temperature",
                    2.0,
                )
            ],
        ).generate()
        combined = next(
            record
            for record in records
            if record.device_id == "zone-1-sensor-1" and record.sequence_number == 1
        )
        self.assertIs(combined.event_label, CriticalityScenario.WATER_DEFICIT)
        self.assertIs(combined.sensor_fault_label, SensorFault.GRADUAL_DRIFT)
        self.assertTrue(combined.delivered)

    def test_burst_loss_keeps_record_but_marks_it_undelivered(self) -> None:
        records = SyntheticTelemetryGenerator(
            self.config,
            faults=[
                FaultInjection(
                    "zone-1-sensor-2", SensorFault.BURST_LOSS, 0, 2
                )
            ],
        ).generate()
        lost = [
            record
            for record in records
            if record.sensor_fault_label is SensorFault.BURST_LOSS
        ]
        self.assertEqual(len(lost), 2)
        self.assertTrue(all(not record.delivered for record in lost))


class ZoneContextTests(unittest.TestCase):
    def test_context_tracks_slope_and_ignores_undelivered_data(self) -> None:
        manager = ZoneContextManager()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index, moisture in enumerate((50.0, 40.0, 30.0)):
            manager.add(
                TelemetryRecord(
                    f"event-{index}",
                    "device-1",
                    "zone-1",
                    start + timedelta(hours=index),
                    index,
                    {
                        "soil_moisture": moisture,
                        "temperature": 25.0,
                        "humidity": 60.0,
                    },
                )
            )
        ignored = TelemetryRecord(
            "lost",
            "device-1",
            "zone-1",
            start + timedelta(hours=3),
            3,
            {"soil_moisture": 0.0},
            delivered=False,
        )
        self.assertFalse(manager.add(ignored))
        snapshot = manager.snapshot("zone-1")
        self.assertEqual(snapshot.record_count, 3)
        self.assertAlmostEqual(
            snapshot.feature_summaries["soil_moisture"]["slope_per_hour"],
            -10.0,
        )
        self.assertEqual(snapshot.derived_features["soil_water_deficit"], 0.0)


class NetworkAndBaselineTests(unittest.TestCase):
    def test_connectivity_sequence_is_seeded(self) -> None:
        first = MarkovConnectivityModel(seed=99)
        second = MarkovConnectivityModel(seed=99)
        self.assertEqual(
            [first.next_state() for _ in range(20)],
            [second.next_state() for _ in range(20)],
        )

    def test_invalid_transition_matrix_is_rejected(self) -> None:
        invalid = {
            state: {target: 0.2 for target in LinkState}
            for state in LinkState
        }
        with self.assertRaises(ValueError):
            MarkovConnectivityModel(transitions=invalid)

    def test_b2_survives_cloud_outage_and_uses_no_cloud_bytes(self) -> None:
        record = TelemetryRecord(
            "event-1",
            "device-1",
            "zone-1",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0,
            {"temperature": 44.0, "humidity": 20.0},
            link_state=LinkState.OFFLINE,
            event_label=CriticalityScenario.HEAT_STRESS,
        )
        cloud = summarize_outcomes(
            BaselineSimulator(Baseline.B0_CLOUD_ONLY).run([record])
        )
        fog = summarize_outcomes(
            BaselineSimulator(Baseline.B2_STATIC_FOG).run([record])
        )
        self.assertEqual(cloud["decision_coverage"], 0.0)
        self.assertEqual(fog["decision_coverage"], 1.0)
        self.assertEqual(fog["bytes_to_cloud"], 0)
        self.assertEqual(fog["per_class"][CriticalityScenario.HEAT_STRESS.value]["f1"], 1.0)

    def test_b0_transmits_and_b2_is_lower_latency(self) -> None:
        record = TelemetryRecord(
            "event-1",
            "device-1",
            "zone-1",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            0,
            {"soil_moisture": 47.0},
        )
        cloud = summarize_outcomes(
            BaselineSimulator(Baseline.B0_CLOUD_ONLY).run([record])
        )
        fog = summarize_outcomes(
            BaselineSimulator(Baseline.B2_STATIC_FOG).run([record])
        )
        self.assertGreater(cloud["bytes_to_cloud"], 0)
        self.assertLess(fog["mean_latency_ms"], cloud["mean_latency_ms"])


if __name__ == "__main__":
    unittest.main()

