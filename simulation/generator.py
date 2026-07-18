"""Seeded synthetic telemetry with independent events and sensor faults."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import random

from models import CriticalityScenario
from simulation.network_model import MarkovConnectivityModel
from simulation.telemetry_schema import LinkState, SensorFault, TelemetryRecord


@dataclass(frozen=True)
class SimulationConfig:
    zone_count: int = 2
    sensors_per_zone: int = 3
    duration_minutes: int = 120
    sample_interval_minutes: int = 10
    seed: int = 7
    start_time: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __post_init__(self) -> None:
        if min(
            self.zone_count,
            self.sensors_per_zone,
            self.duration_minutes,
            self.sample_interval_minutes,
        ) < 1:
            raise ValueError("simulation dimensions must be positive")
        if self.start_time.tzinfo is None:
            raise ValueError("start_time must be timezone-aware")

    @property
    def steps(self) -> int:
        return math.ceil(self.duration_minutes / self.sample_interval_minutes)


@dataclass(frozen=True)
class EventInjection:
    zone_id: str
    event: CriticalityScenario
    start_step: int
    duration_steps: int


@dataclass(frozen=True)
class FaultInjection:
    device_id: str
    fault: SensorFault
    start_step: int
    duration_steps: int
    field: str = "soil_moisture"
    magnitude: float = 8.0


class SyntheticTelemetryGenerator:
    def __init__(
        self,
        config: SimulationConfig,
        events: list[EventInjection] | None = None,
        faults: list[FaultInjection] | None = None,
        connectivity: MarkovConnectivityModel | None = None,
    ) -> None:
        self.config = config
        self.events = events or []
        self.faults = faults or []
        self.connectivity = connectivity or MarkovConnectivityModel(seed=config.seed)
        self._validate_injections()

    def _validate_injections(self) -> None:
        valid_zones = {f"zone-{index + 1}" for index in range(self.config.zone_count)}
        valid_devices = {
            f"{zone}-sensor-{sensor + 1}"
            for zone in valid_zones
            for sensor in range(self.config.sensors_per_zone)
        }
        occupied_events: set[tuple[str, int]] = set()
        for injection in self.events:
            if injection.zone_id not in valid_zones:
                raise ValueError(f"unknown event zone {injection.zone_id}")
            self._validate_schedule(injection.start_step, injection.duration_steps)
            for step in range(
                injection.start_step, injection.start_step + injection.duration_steps
            ):
                key = (injection.zone_id, step)
                if key in occupied_events:
                    raise ValueError("overlapping event injections are not supported")
                occupied_events.add(key)
        occupied_faults: set[tuple[str, int]] = set()
        for injection in self.faults:
            if injection.device_id not in valid_devices:
                raise ValueError(f"unknown fault device {injection.device_id}")
            if injection.fault is SensorFault.NONE:
                raise ValueError("NONE is not a fault injection")
            self._validate_schedule(injection.start_step, injection.duration_steps)
            for step in range(
                injection.start_step, injection.start_step + injection.duration_steps
            ):
                key = (injection.device_id, step)
                if key in occupied_faults:
                    raise ValueError("overlapping fault injections are not supported")
                occupied_faults.add(key)

    def _validate_schedule(self, start_step: int, duration_steps: int) -> None:
        if start_step < 0 or duration_steps < 1:
            raise ValueError("injection start must be non-negative and duration positive")
        if start_step + duration_steps > self.config.steps:
            raise ValueError("injection exceeds simulation duration")

    def generate(self) -> list[TelemetryRecord]:
        rng = random.Random(self.config.seed)
        records: list[TelemetryRecord] = []
        sequence_by_device: dict[str, int] = {}
        for step in range(self.config.steps):
            link_state = self.connectivity.state
            timestamp = self.config.start_time + timedelta(
                minutes=step * self.config.sample_interval_minutes
            )
            for zone_index in range(self.config.zone_count):
                zone_id = f"zone-{zone_index + 1}"
                event = self._event_for(zone_id, step)
                for sensor_index in range(self.config.sensors_per_zone):
                    device_id = f"{zone_id}-sensor-{sensor_index + 1}"
                    sequence = sequence_by_device.get(device_id, 0)
                    readings = self._normal_readings(rng, step, sensor_index)
                    actuator_state = {"valve_open": False, "pump_active": False}
                    self._apply_event(readings, actuator_state, event)
                    fault = self._fault_for(device_id, step)
                    delivered = self._apply_fault(readings, fault, step, rng)
                    confidence = 0.94 if event is not CriticalityScenario.NORMAL else 0.90
                    if fault is not None:
                        confidence = max(0.50, confidence - 0.20)
                    records.append(
                        TelemetryRecord(
                            event_id=f"evt-{step:04d}-{zone_index + 1}-{sensor_index + 1}",
                            device_id=device_id,
                            zone_id=zone_id,
                            timestamp=timestamp,
                            sequence_number=sequence,
                            readings=readings,
                            tinyml_class=event.value,
                            tinyml_confidence=confidence,
                            actuator_state=actuator_state,
                            link_state=link_state,
                            event_label=event,
                            sensor_fault_label=(fault.fault if fault else SensorFault.NONE),
                            delivered=delivered,
                        )
                    )
                    sequence_by_device[device_id] = sequence + 1
            self.connectivity.next_state()
        return records

    def _event_for(self, zone_id: str, step: int) -> CriticalityScenario:
        for injection in self.events:
            if (
                injection.zone_id == zone_id
                and injection.start_step <= step < injection.start_step + injection.duration_steps
            ):
                return injection.event
        return CriticalityScenario.NORMAL

    def _fault_for(self, device_id: str, step: int) -> FaultInjection | None:
        for injection in self.faults:
            if (
                injection.device_id == device_id
                and injection.start_step <= step < injection.start_step + injection.duration_steps
            ):
                return injection
        return None

    @staticmethod
    def _normal_readings(
        rng: random.Random, step: int, sensor_index: int
    ) -> dict[str, float | bool | None]:
        daily_phase = math.sin(step / 12.0 * 2.0 * math.pi)
        return {
            "temperature": round(24.0 + 3.0 * daily_phase + rng.uniform(-0.4, 0.4), 2),
            "humidity": round(62.0 - 5.0 * daily_phase + rng.uniform(-1.0, 1.0), 2),
            "rainfall": 0.0,
            "soil_moisture": round(47.0 + rng.uniform(-1.5, 1.5), 2),
            "ph": round(6.5 + rng.uniform(-0.08, 0.08), 2),
            "nitrogen": round(42.0 + rng.uniform(-2.0, 2.0), 2),
            "phosphorus": round(35.0 + rng.uniform(-2.0, 2.0), 2),
            "potassium": round(39.0 + rng.uniform(-2.0, 2.0), 2),
            "salinity": round(1.1 + rng.uniform(-0.08, 0.08), 2),
            "leaf_wetness": round(18.0 + rng.uniform(-2.0, 2.0), 2),
            "pest_pressure": round(0.08 + rng.uniform(0.0, 0.04), 3),
            "tank_level": round(78.0 - step * 0.2 + sensor_index * 0.1, 2),
            "irrigation_flow": 0.0,
            "equipment_health": 0.98,
        }

    @staticmethod
    def _apply_event(
        readings: dict[str, float | bool | None],
        actuator_state: dict[str, bool],
        event: CriticalityScenario,
    ) -> None:
        if event is CriticalityScenario.WATER_DEFICIT:
            readings.update(soil_moisture=16.0, humidity=34.0)
        elif event is CriticalityScenario.FLOODING:
            readings.update(soil_moisture=96.0, rainfall=38.0, humidity=95.0)
        elif event is CriticalityScenario.HEAT_STRESS:
            readings.update(temperature=44.0, humidity=22.0)
        elif event is CriticalityScenario.DISEASE_RISK:
            readings.update(humidity=93.0, leaf_wetness=91.0)
        elif event is CriticalityScenario.PEST_INFESTATION:
            readings.update(pest_pressure=0.94)
        elif event is CriticalityScenario.SOIL_DEGRADATION:
            readings.update(ph=4.4, salinity=5.8)
        elif event is CriticalityScenario.EQUIPMENT_FAILURE:
            readings.update(irrigation_flow=0.0, equipment_health=0.12)
            actuator_state.update(valve_open=True, pump_active=True)

    @staticmethod
    def _apply_fault(
        readings: dict[str, float | bool | None],
        fault: FaultInjection | None,
        step: int,
        rng: random.Random,
    ) -> bool:
        if fault is None:
            return True
        if fault.field not in readings and fault.fault is not SensorFault.BURST_LOSS:
            raise ValueError(f"fault field {fault.field} is not present")
        if fault.fault is SensorFault.RANDOM_DROPOUT:
            if rng.random() < 0.65:
                readings[fault.field] = None
        elif fault.fault is SensorFault.GRADUAL_DRIFT:
            current = readings[fault.field]
            if isinstance(current, (int, float)):
                progress = step - fault.start_step + 1
                readings[fault.field] = round(current + fault.magnitude * progress, 3)
        elif fault.fault is SensorFault.STUCK_AT:
            readings[fault.field] = fault.magnitude
        elif fault.fault is SensorFault.BURST_LOSS:
            return False
        return True
