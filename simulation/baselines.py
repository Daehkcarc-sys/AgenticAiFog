"""Runnable B0–B5 experiment baselines with energy model, LLM cost, twin bridge."""

from __future__ import annotations

import dataclasses
from collections import deque
from dataclasses import dataclass
from enum import Enum
import json
from typing import Any

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
    # Component-level energy breakdown (millijoules)
    edge_energy_mj: float = 0.0
    fog_energy_mj: float = 0.0
    cloud_energy_mj: float = 0.0
    # LLM API cost proxy (USD per inference)
    llm_cost: float = 0.0
    # Digital twin risk index after this decision
    twin_risk_index: float | None = None


class StaticEventClassifier:
    """Transparent static rules used by B2 and as the B0 cloud model."""

    def classify(self, record: TelemetryRecord) -> CriticalityScenario:
        return self._classify_values(record.readings, record.actuator_state)

    def classify_with_zone(
        self,
        record: TelemetryRecord,
        zone_means: dict[str, float],
    ) -> CriticalityScenario:
        """B2 zone-fusion variant: blend individual reading with zone window average."""
        merged = dict(record.readings)
        for key, zone_val in zone_means.items():
            if key in merged and isinstance(merged[key], (int, float)):
                merged[key] = (float(merged[key]) + zone_val) / 2.0
        return self._classify_values(merged, record.actuator_state)

    def _classify_values(
        self,
        values: dict[str, Any],
        actuator_state: dict[str, Any],
    ) -> CriticalityScenario:
        def number(name: str, default: float = 0.0) -> float:
            value = values.get(name)
            return float(value) if isinstance(value, (int, float)) else default

        if (
            bool(actuator_state.get("valve_open"))
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


class _ZoneWindow:
    """Rolling window of numeric readings per zone for B2 zone fusion."""

    def __init__(self, window: int = 10) -> None:
        self._window = window
        self._readings: dict[str, deque[dict[str, float]]] = {}

    def add(self, record: TelemetryRecord) -> None:
        zone = record.zone_id
        if zone not in self._readings:
            self._readings[zone] = deque(maxlen=self._window)
        numeric = {
            k: float(v)
            for k, v in record.readings.items()
            if isinstance(v, (int, float))
        }
        if numeric:
            self._readings[zone].append(numeric)

    def means(self, zone_id: str) -> dict[str, float]:
        buf = self._readings.get(zone_id)
        if not buf:
            return {}
        all_keys = {k for r in buf for k in r}
        result = {}
        for k in all_keys:
            vals = [r[k] for r in buf if k in r]
            result[k] = sum(vals) / len(vals)
        return result


def _transmission_energy_mj(payload_bytes: int, link_state: LinkState) -> float:
    """Energy cost of transmitting payload over the given link (millijoules)."""
    if link_state is LinkState.OFFLINE:
        return 0.0
    if link_state is LinkState.NTN:
        # High-gain satellite antenna: ~50 μJ/byte
        return payload_bytes * 0.05
    # Terrestrial WiFi/4G: ~1 μJ/byte
    return payload_bytes * 0.001


def _fog_summary_payload(
    record: TelemetryRecord,
    outcome: DecisionOutcome,
) -> dict[str, Any]:
    """Build a FogSummaryContract-compatible dict from an outcome."""
    return {
        "sensor_id": record.device_id,
        "zone_id": record.zone_id,
        "scenario": outcome.predicted_event.value if outcome.predicted_event else None,
        "severity": "high" if outcome.predicted_event and outcome.predicted_event is not CriticalityScenario.NORMAL else None,
        "critical": outcome.predicted_event is CriticalityScenario.EQUIPMENT_FAILURE if outcome.predicted_event else False,
        "decision": outcome.decision_source,
        "decision_source": outcome.decision_source,
        "confidence": outcome.trust_score,
        "result": "accepted" if outcome.decision_made else "rejected",
        "trust_score": outcome.trust_score,
        "raw_readings": {k: float(v) for k, v in record.readings.items() if isinstance(v, (int, float))},
    }


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
        twin: "Any | None" = None,
        zone_fusion: bool = True,
        high_freq_factor: int = 1,
    ) -> None:
        self.baseline = Baseline(baseline)
        self.profiles = profiles or DEFAULT_PROFILES
        self.classifier = classifier or StaticEventClassifier()
        self._twin = twin         # optional DigitalTwinEngine for B5
        self._zone_window = _ZoneWindow() if zone_fusion else None
        # B0 raw-stream multiplier: how many raw samples per aggregated record
        self._high_freq_factor = max(1, high_freq_factor)

    def run_with_twin(self, records: list[TelemetryRecord]) -> tuple[list[DecisionOutcome], dict[str, Any]]:
        """Run simulation and return (outcomes, twin_dashboard_state).

        If no twin was supplied at construction the dashboard dict is empty.
        """
        outcomes = self.run(records)
        dashboard = self._twin.dashboard_state() if self._twin is not None else {}
        return outcomes, dashboard

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

        # Update zone window for B2 zone fusion (happens at record-arrival time)
        if self._zone_window is not None:
            self._zone_window.add(record)

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
                    edge_energy_mj=0.5,
                )
            )
            return

        # ── B2: Static fog with zone-window fusion ───────────────────────────
        if self.baseline is Baseline.B2_STATIC_FOG:
            processing_ms = 15.0
            yield environment.timeout(processing_ms)
            if self._zone_window is not None:
                zone_means = self._zone_window.means(record.zone_id)
                predicted = self.classifier.classify_with_zone(record, zone_means)
                reason = "zone-fused fog decision"
            else:
                predicted = self.classifier.classify(record)
                reason = "static fog decision"
            outcomes.append(
                DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    predicted,
                    True,
                    processing_ms,
                    0,
                    record.link_state,
                    0.0,
                    10.0,
                    reason,
                    decision_source="rule",
                    fog_energy_mj=2.0,
                )
            )
            return

        # ── B4: Trust-aware static fog ───────────────────────────────────────
        if self.baseline is Baseline.B4_TRUST_FOG:
            trust = _simulated_trust(record)
            fog_ms = 15.0
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
                        f"trust={trust:.2f} below threshold; rejected",
                        trust_score=trust,
                        decision_source="trust_reject",
                        edge_energy_mj=0.5,
                        fog_energy_mj=1.5,
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
                        edge_energy_mj=0.5,
                        fog_energy_mj=3.0,
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
        # B0 high-frequency raw stream multiplier
        effective_bytes = payload_bytes * self._high_freq_factor
        network_ms = profile.transmission_delay_ms(effective_bytes)
        tx_energy = _transmission_energy_mj(effective_bytes, record.link_state)

        # ── B3: Direct LLM (cloud) ───────────────────────────────────────────
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
                    effective_bytes,
                    record.link_state,
                    profile.transmission_cost(effective_bytes),
                    120.0,
                    "cloud LLM decision",
                    decision_source="llm",
                    edge_energy_mj=0.5,
                    cloud_energy_mj=20.0 + tx_energy,
                    llm_cost=0.002,
                )
            )
            return

        # ── B5: Full system with digital twin integration ────────────────────
        if self.baseline is Baseline.B5_FULL_SYSTEM:
            trust = _simulated_trust(record)
            fog_ms = 20.0
            yield environment.timeout(fog_ms)

            if trust < 0.5:
                outcome = DecisionOutcome(
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
                    edge_energy_mj=0.5,
                    fog_energy_mj=2.0,
                )
                outcomes.append(outcome)
                if self._twin is not None:
                    payload = _fog_summary_payload(record, outcome)
                    self._twin.apply_fog_summary(payload)
                    twin_zone = self._twin.farm.zones.get(record.zone_id)
                    if twin_zone is not None:
                        outcomes[-1] = dataclasses.replace(
                            outcome, twin_risk_index=twin_zone.risk_index
                        )
                return

            if trust >= 0.8 or record.link_state is not LinkState.TERRESTRIAL:
                predicted = self.classifier.classify(record)
                if self._zone_window is not None:
                    zone_means = self._zone_window.means(record.zone_id)
                    predicted = self.classifier.classify_with_zone(record, zone_means)
                outcome = DecisionOutcome(
                    self.baseline,
                    record.event_id,
                    record.event_label,
                    predicted,
                    True,
                    fog_ms,
                    0,
                    record.link_state,
                    0.0,
                    12.0,
                    f"trust={trust:.2f} local fog decision",
                    trust_score=trust,
                    decision_source="rule",
                    edge_energy_mj=0.5,
                    fog_energy_mj=5.0,
                )
                if self._twin is not None:
                    payload = _fog_summary_payload(record, outcome)
                    self._twin.apply_fog_summary(payload)
                    twin_zone = self._twin.farm.zones.get(record.zone_id)
                    if twin_zone is not None:
                        outcome = dataclasses.replace(
                            outcome, twin_risk_index=twin_zone.risk_index
                        )
                outcomes.append(outcome)
                return

            # MEDIUM trust + terrestrial: escalate to cloud
            cloud_ms = 50.0
            yield environment.timeout(network_ms + cloud_ms)
            outcome = DecisionOutcome(
                self.baseline,
                record.event_id,
                record.event_label,
                self.classifier.classify(record),
                True,
                fog_ms + network_ms + cloud_ms,
                effective_bytes,
                record.link_state,
                profile.transmission_cost(effective_bytes),
                60.0,
                f"trust={trust:.2f} escalated to cloud",
                trust_score=trust,
                decision_source="cloud",
                edge_energy_mj=0.5,
                fog_energy_mj=5.0,
                cloud_energy_mj=20.0 + tx_energy,
            )
            if self._twin is not None:
                payload = _fog_summary_payload(record, outcome)
                self._twin.apply_fog_summary(payload)
                twin_zone = self._twin.farm.zones.get(record.zone_id)
                if twin_zone is not None:
                    outcome = dataclasses.replace(
                        outcome, twin_risk_index=twin_zone.risk_index
                    )
            outcomes.append(outcome)
            return

        # ── B0: Cloud-only with raw-stream multiplier ────────────────────────
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
                effective_bytes,
                record.link_state,
                profile.transmission_cost(effective_bytes),
                100.0,
                "cloud decision" if self._high_freq_factor == 1 else f"cloud raw-stream x{self._high_freq_factor}",
                decision_source="rule",
                cloud_energy_mj=20.0 + tx_energy,
            )
        )

