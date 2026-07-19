"""Deterministic three-state fog-to-cloud connectivity model."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Mapping

from simulation.telemetry_schema import LinkState


@dataclass(frozen=True)
class NetworkProfile:
    bandwidth_bytes_per_second: float
    latency_ms: float
    cost_per_megabyte: float

    def transmission_delay_ms(self, payload_bytes: int) -> float:
        if payload_bytes < 0:
            raise ValueError("payload_bytes must be non-negative")
        if self.bandwidth_bytes_per_second <= 0:
            return math.inf
        return self.latency_ms + payload_bytes / self.bandwidth_bytes_per_second * 1000.0

    def transmission_cost(self, payload_bytes: int) -> float:
        if payload_bytes < 0:
            raise ValueError("payload_bytes must be non-negative")
        return payload_bytes / 1_000_000.0 * self.cost_per_megabyte


DEFAULT_PROFILES: dict[LinkState, NetworkProfile] = {
    LinkState.TERRESTRIAL: NetworkProfile(10_000_000, 40.0, 0.01),
    LinkState.NTN: NetworkProfile(500_000, 650.0, 1.50),
    LinkState.OFFLINE: NetworkProfile(0.0, math.inf, 0.0),
}

DEFAULT_TRANSITIONS: dict[LinkState, dict[LinkState, float]] = {
    LinkState.TERRESTRIAL: {
        LinkState.TERRESTRIAL: 0.85,
        LinkState.NTN: 0.10,
        LinkState.OFFLINE: 0.05,
    },
    LinkState.NTN: {
        LinkState.TERRESTRIAL: 0.20,
        LinkState.NTN: 0.65,
        LinkState.OFFLINE: 0.15,
    },
    LinkState.OFFLINE: {
        LinkState.TERRESTRIAL: 0.25,
        LinkState.NTN: 0.25,
        LinkState.OFFLINE: 0.50,
    },
}


class MarkovConnectivityModel:
    """Seeded Markov chain for terrestrial, NTN, and offline states."""

    def __init__(
        self,
        seed: int = 0,
        initial_state: LinkState = LinkState.TERRESTRIAL,
        transitions: Mapping[LinkState, Mapping[LinkState, float]] | None = None,
        profiles: Mapping[LinkState, NetworkProfile] | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self.state = LinkState(initial_state)
        self.transitions = {
            LinkState(source): {
                LinkState(target): float(probability)
                for target, probability in row.items()
            }
            for source, row in (transitions or DEFAULT_TRANSITIONS).items()
        }
        self.profiles = {
            LinkState(state): profile
            for state, profile in (profiles or DEFAULT_PROFILES).items()
        }
        self._validate()

    def _validate(self) -> None:
        states = set(LinkState)
        if set(self.transitions) != states:
            raise ValueError("transition matrix must define every LinkState")
        if set(self.profiles) != states:
            raise ValueError("network profiles must define every LinkState")
        for source, row in self.transitions.items():
            if set(row) != states:
                raise ValueError(f"transition row {source.value} must target every state")
            if any(probability < 0 for probability in row.values()):
                raise ValueError("transition probabilities cannot be negative")
            if not math.isclose(sum(row.values()), 1.0, abs_tol=1e-9):
                raise ValueError(f"transition row {source.value} must sum to 1")

    def profile(self, state: LinkState | None = None) -> NetworkProfile:
        return self.profiles[LinkState(state or self.state)]

    def next_state(self) -> LinkState:
        sample = self._rng.random()
        cumulative = 0.0
        for target, probability in self.transitions[self.state].items():
            cumulative += probability
            if sample <= cumulative:
                self.state = target
                return target
        self.state = list(self.transitions[self.state])[-1]
        return self.state

