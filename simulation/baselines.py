"""Runnable B0 cloud-only and B2 static-fog experiment baselines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json

import simpy

from models import CriticalityScenario
from simulation.network_model import DEFAULT_PROFILES, NetworkProfile
from simulation.telemetry_schema import LinkState, TelemetryRecord


class Baseline(str, Enum):
    B0_CLOUD_ONLY = "B0"
    B1_EDGE_ONLY = "B1"
    B2_STATIC_FOG = "B2"
    B3_DIRECT_LLM = "B3"
    B4_TRUST_FOG = "B4"
    B5_FULL_SYSTEM = "B5"


@dataclass(frozen=True)
class DecisionOutcome:
    baseline: Baseline
    event_id: str
    true_event: CriticalityScenario
    predicted_event: CriticalityScenario | None
    decision_made: bool
    latency_ms: float | None
    bytes_to_cloud: int
    link_state: LinkState
    communication_cost: float
    energy_units: float
    reason: str
    # Optional extended fields for B4/B5
    trust_score: float | None = None
    decision_source: str | None = None


class StaticEventClassifier:
    """Transparent static rules used by B2 and as the B0 cloud model."""

    def classify(self, record: TelemetryRecord) -> CriticalityScenario:
        values = record.readings

        def number(name: str, default: float = 0.0) -> float:
            value = values.get(name)
            return float(value) if isinstance(value, (int, float)) else default

        if (
            bool(record.actuator_state.get("valve_open"))
            and number("irrigation_flow") < 0.2
        ) or number("equipment_health", 1.0) < 0.4:
            return CriticalityScenario.EQUIPMENT_FAILURE
        if number("rainfall") > 20 or number("soil_moisture") > 88:
            return CriticalityScenario.FLOODING
        if number("temperature") >= 40:
            return CriticalityScenario.HEAT_STRESS
        if number("humidity") >= 88 and number("leaf_wetness") >= 75:
            return CriticalityScenario.DISEASE_RISK
        if number("pest_pressure") >= 0.7:
            return CriticalityScenario.PEST_INFESTATION
        if number("ph", 6.5) < 5.0 or number("salinity") >= 4.0:
            return CriticalityScenario.SOIL_DEGRADATION
        if number("soil_moisture", 50.0) <= 22:
            return CriticalityScenario.WATER_DEFICIT
        return CriticalityScenario.NORMAL


def _simulated_trust(record: TelemetryRecord) -> float:
    """Estimate a trust score from the simulation ground truth.

    In a real deployment the TrustScoreAgent computes this from freshness,
    identity, and reading/recommendation consistency. Here we use the known
    fault label as a proxy so B4/B5 can model trust-gated routing.
    """
    from simulation.telemetry_schema import SensorFault
    fault = record.sensor_fault_label
    if fault is SensorFault.NONE:
        return 1.0
    if fault is SensorFault.GRADUAL_DRIFT:
        return 0.60   # MEDIUM — drift is not immediately obvious
    if fault is SensorFault.RANDOM_DROPOUT:
        return 0.35   # LOW — frequent missing readings
    if fault is SensorFault.STUCK_AT:
        return 0.40   # LOW — stale identical values
    if fault is SensorFault.BURST_LOSS:
        return 0.25   # LOW — record survived but delivery was unreliable
    return 0.80


class BaselineSimulator:
    """Discrete-event execution with communication and processing delays."""

    def __init__(
        self,
        baseline: Baseline,
        profiles: dict[LinkState, NetworkProfile] | None = None,
        classifier: StaticEventClassifier | None = None,
    ) -> None:
        self.baseline = Baseline(baseline)
        self.profiles = profiles or DEFAULT_PROFILES
        self.classifier = classifier or StaticEventClassifier()

    def run(self, records: list[TelemetryRecord]) -> list[DecisionOutcome]:
        if not records:
            return []
        environment = simpy.Environment()
        outcomes: list[DecisionOutcome] = []
        start = min(record.timestamp for record in records)
        for record in records:
            release_ms = (record.timestamp - start).total_seconds() * 1000.0
            environment.process(self._process(environment, record, release_ms, outcomes))
        environment.run()
        return outcomes

    def _process(
        self,
        environment: simpy.Environment,
        record: TelemetryRecord,
        release_ms: float,
        outcomes: list[DecisionOutcome],
    ):
        yield environment.timeout(release_ms)
        if not record.delivered:
            outcomes.append(
                DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    None,
                    False,
                    None,
                    0,
                    record.link_state,
                    0.0,
                    0.0,
                    "sensor-to-fog delivery failed",
                )
            )
            return

        # ── B1: Edge-only ────────────────────────────────────────────────────
        # Decision made at the edge from the TinyML class alone; no fog,
        # no cloud, always available regardless of link state.
        if self.baseline is Baseline.B1_EDGE_ONLY:
            edge_ms = 5.0
            yield environment.timeout(edge_ms)
            try:
                predicted = CriticalityScenario(record.tinyml_class)
            except ValueError:
                predicted = CriticalityScenario.NORMAL
            outcomes.append(
                DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    predicted,
                    True,
                    edge_ms,
                    0,
                    record.link_state,
                    0.0,
                    5.0,
                    "edge tinyml decision",
                    trust_score=1.0,
                    decision_source="tinyml",
                )
            )
            return

        # ── B2: Static fog ───────────────────────────────────────────────────
        if self.baseline is Baseline.B2_STATIC_FOG:
            processing_ms = 15.0
            yield environment.timeout(processing_ms)
            outcomes.append(
                DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    self.classifier.classify(record),
                    True,
                    processing_ms,
                    0,
                    record.link_state,
                    0.0,
                    10.0,
                    "static fog decision",
                    decision_source="rule",
                )
            )
            return

        # ── B4: Trust-aware static fog ───────────────────────────────────────
        # Same as B2 but rejects or escalates low-trust readings.
        if self.baseline is Baseline.B4_TRUST_FOG:
            trust = _simulated_trust(record)
            fog_ms = 15.0
            yield environment.timeout(fog_ms)
            if trust < 0.5:
                # LOW trust: reject locally, no cloud upload
                outcomes.append(
                    DecisionOutcome(
                        self.baseline,
                        record.event_id,
                        record.event_label,
                        None,
                        False,
                        fog_ms,
                        0,
                        record.link_state,
                        0.0,
                        8.0,
                        f"trust={trust:.2f} below threshold; rejected",
                        trust_score=trust,
                        decision_source="trust_reject",
                    )
                )
            else:
                outcomes.append(
                    DecisionOutcome(
                        self.baseline,
                        record.event_id,
                        record.event_label,
                        self.classifier.classify(record),
                        True,
                        fog_ms,
                        0,
                        record.link_state,
                        0.0,
                        10.0,
                        f"trust={trust:.2f} accepted; local fog decision",
                        trust_score=trust,
                        decision_source="rule",
                    )
                )
            return

        profile = self.profiles[record.link_state]
        if record.link_state is LinkState.OFFLINE:
            outcomes.append(
                DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    None,
                    False,
                    None,
                    0,
                    record.link_state,
                    0.0,
                    0.0,
                    "cloud unavailable while link is offline",
                )
            )
            return

        payload_bytes = len(
            json.dumps(record.to_dict(), separators=(",", ":")).encode("utf-8")
        )
        network_ms = profile.transmission_delay_ms(payload_bytes)

        # ── B3: Direct LLM (cloud) ───────────────────────────────────────────
        # Like B0 but adds simulated LLM inference time on top of cloud RTT.
        if self.baseline is Baseline.B3_DIRECT_LLM:
            llm_ms = 200.0
            cloud_processing_ms = 50.0 + llm_ms
            yield environment.timeout(network_ms + cloud_processing_ms)
            outcomes.append(
                DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    self.classifier.classify(record),
                    True,
                    network_ms + cloud_processing_ms,
                    payload_bytes,
                    record.link_state,
                    profile.transmission_cost(payload_bytes),
                    120.0,
                    "cloud LLM decision",
                    decision_source="llm",
                )
            )
            return

        # ── B5: Full system ──────────────────────────────────────────────────
        # Trust-gated fog with zone context and NTN-aware routing.
        #   HIGH trust → local fog decision (like B4 path)
        #   MEDIUM + terrestrial → cloud escalation (like B0)
        #   MEDIUM + NTN/offline → local fog fallback
        #   LOW trust → reject
        if self.baseline is Baseline.B5_FULL_SYSTEM:
            trust = _simulated_trust(record)
            fog_ms = 20.0   # local pipeline overhead
            yield environment.timeout(fog_ms)

            if trust < 0.5:
                outcomes.append(
                    DecisionOutcome(
                        self.baseline,
                        record.event_id,
                        record.event_label,
                        None,
                        False,
                        fog_ms,
                        0,
                        record.link_state,
                        0.0,
                        8.0,
                        f"trust={trust:.2f} rejected by fog pipeline",
                        trust_score=trust,
                        decision_source="trust_reject",
                    )
                )
                return

            if trust >= 0.8 or record.link_state is not LinkState.TERRESTRIAL:
                # HIGH trust or NTN/offline: act/validate locally
                outcomes.append(
                    DecisionOutcome(
                        self.baseline,
                        record.event_id,
                        record.event_label,
                        self.classifier.classify(record),
                        True,
                        fog_ms,
                        0,
                        record.link_state,
                        0.0,
                        12.0,
                        f"trust={trust:.2f} local fog decision",
                        trust_score=trust,
                        decision_source="rule",
                    )
                )
                return

            # MEDIUM trust + terrestrial: escalate to cloud
            cloud_ms = 50.0
            yield environment.timeout(network_ms + cloud_ms)
            outcomes.append(
                DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    self.classifier.classify(record),
                    True,
                    fog_ms + network_ms + cloud_ms,
                    payload_bytes,
                    record.link_state,
                    profile.transmission_cost(payload_bytes),
                    60.0,
                    f"trust={trust:.2f} escalated to cloud",
                    trust_score=trust,
                    decision_source="cloud",
                )
            )
            return

        # ── B0: Cloud-only (default) ─────────────────────────────────────────
        cloud_processing_ms = 50.0
        yield environment.timeout(network_ms + cloud_processing_ms)
        outcomes.append(
            DecisionOutcome(
                self.baseline,
                record.event_id,
                record.event_label,
                self.classifier.classify(record),
                True,
                network_ms + cloud_processing_ms,
                payload_bytes,
                record.link_state,
                profile.transmission_cost(payload_bytes),
                100.0,
                "cloud decision",
                decision_source="rule",
            )
        )

