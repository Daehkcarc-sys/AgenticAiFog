"""Runtime metrics collection for the fog pipeline.

Provides per-agent latency tracking, trust-score distributions,
decision-outcome histograms, cache effectiveness, and connectivity
statistics suitable for academic benchmarking and publication figures.

Usage::

    metrics = PipelineMetrics()
    with metrics.measure("trust_score"):
        result = trust_score_agent.run(...)

    # After the run:
    metrics.report()          # prints summary to stdout
    metrics.to_dict()         # returns serializable dict for JSON export
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from contextlib import contextmanager
from time import perf_counter
from typing import Iterator


class PipelineMetrics:
    """Collector for fog pipeline runtime statistics.

    Tracks per-agent latencies, trust-score distributions, scenario
    frequencies, decision outcomes, decision sources, cache efficiency,
    and degraded-mode activations across a pipeline session.
    """

    def __init__(self) -> None:
        self._agent_latencies: defaultdict[str, list[float]] = defaultdict(list)
        self._trust_scores: list[float] = []
        self._scenarios: defaultdict[str, int] = defaultdict(int)
        self._decisions: defaultdict[str, int] = defaultdict(int)
        self._actions: defaultdict[str, int] = defaultdict(int)
        self._results: defaultdict[str, int] = defaultdict(int)
        self._decision_sources: defaultdict[str, int] = defaultdict(int)
        self._total_readings: int = 0
        # Cache & connectivity counters (updated externally)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._degraded_activations: int = 0

    @contextmanager
    def measure(self, agent_name: str) -> Iterator[None]:
        """Context manager that records the wall-clock duration of a block.

        Args:
            agent_name: Label for the agent being measured (e.g. "trust_score").
        """
        start = perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (perf_counter() - start) * 1000
            self._agent_latencies[agent_name].append(elapsed_ms)

    def record_reading(
        self,
        trust_score: float,
        scenario: str,
        decision: str,
        action: str,
        result: str,
        source: str = "",
    ) -> None:
        """Record the outcome of a single pipeline reading."""
        self._total_readings += 1
        self._trust_scores.append(trust_score)
        self._scenarios[scenario] += 1
        self._decisions[decision] += 1
        self._actions[action] += 1
        self._results[result] += 1
        if source:
            self._decision_sources[source] += 1

    def set_cache_stats(self, *, hits: int = 0, misses: int = 0) -> None:
        """Synchronize absolute cache counters without cumulative inflation."""
        self._cache_hits = hits
        self._cache_misses = misses

    def set_degraded_activations(self, count: int) -> None:
        """Synchronize the absolute degraded-mode activation counter."""
        self._degraded_activations = count

    def report(self) -> str:
        """Return a formatted summary string suitable for console output."""
        lines: list[str] = []
        lines.append("=" * 50)
        lines.append("        FOG PIPELINE METRICS REPORT")
        lines.append("=" * 50)
        lines.append(f"  Total readings      : {self._total_readings}")

        # Trust score distribution
        if self._trust_scores:
            lines.append("-" * 50)
            lines.append("  Trust Score Distribution:")
            lines.append(f"    Mean   : {statistics.mean(self._trust_scores):.4f}")
            lines.append(f"    Median : {statistics.median(self._trust_scores):.4f}")
            lines.append(
                f"    Stdev  : {statistics.stdev(self._trust_scores):.4f}"
                if len(self._trust_scores) > 1
                else "    Stdev  : N/A"
            )
            lines.append(f"    Min    : {min(self._trust_scores):.4f}")
            lines.append(f"    Max    : {max(self._trust_scores):.4f}")

        # Per-agent latencies
        if self._agent_latencies:
            lines.append("-" * 50)
            lines.append("  Agent Latencies (ms):")
            for agent_name, latencies in sorted(self._agent_latencies.items()):
                avg = statistics.mean(latencies)
                med = statistics.median(latencies)
                p99 = (
                    sorted(latencies)[int(len(latencies) * 0.99)]
                    if len(latencies) > 1
                    else latencies[0]
                )
                lines.append(
                    f"    {agent_name:<20s}  avg={avg:8.2f}  "
                    f"median={med:8.2f}  p99={p99:8.2f}"
                )

        # Scenario distribution
        if self._scenarios:
            lines.append("-" * 50)
            lines.append("  Scenario Distribution:")
            for scenario, count in sorted(self._scenarios.items(), key=lambda x: -x[1]):
                pct = (count / self._total_readings) * 100 if self._total_readings else 0
                lines.append(f"    {scenario:<25s}  {count:5d}  ({pct:5.1f}%)")

        # Decision distribution
        if self._decisions:
            lines.append("-" * 50)
            lines.append("  Decision Distribution:")
            for decision, count in sorted(self._decisions.items(), key=lambda x: -x[1]):
                pct = (count / self._total_readings) * 100 if self._total_readings else 0
                lines.append(f"    {decision:<25s}  {count:5d}  ({pct:5.1f}%)")

        # Decision source distribution
        if self._decision_sources:
            lines.append("-" * 50)
            lines.append("  Decision Source:")
            for source, count in sorted(self._decision_sources.items(), key=lambda x: -x[1]):
                pct = (count / self._total_readings) * 100 if self._total_readings else 0
                lines.append(f"    {source:<25s}  {count:5d}  ({pct:5.1f}%)")

        # LLM-free decision rate
        if self._total_readings > 0 and self._decision_sources:
            llm_free = sum(
                v for k, v in self._decision_sources.items() if k != "llm"
            )
            pct = (llm_free / self._total_readings) * 100
            lines.append("-" * 50)
            lines.append(f"  LLM-Free Decisions   : {llm_free}/{self._total_readings}  ({pct:.1f}%)")

        # Cache effectiveness
        cache_total = self._cache_hits + self._cache_misses
        if cache_total > 0:
            lines.append("-" * 50)
            lines.append("  Similarity Cache:")
            lines.append(f"    Hits               : {self._cache_hits}")
            lines.append(f"    Misses             : {self._cache_misses}")
            lines.append(f"    Hit rate           : {self._cache_hits / cache_total:.1%}")

        # Degraded mode
        if self._degraded_activations > 0:
            lines.append("-" * 50)
            lines.append(f"  Degraded Mode        : {self._degraded_activations} activation(s)")

        lines.append("=" * 50)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Return all metrics as a JSON-serializable dictionary."""
        agent_stats = {}
        for name, latencies in self._agent_latencies.items():
            agent_stats[name] = {
                "count": len(latencies),
                "avg_ms": round(statistics.mean(latencies), 3),
                "median_ms": round(statistics.median(latencies), 3),
                "p99_ms": (
                    round(sorted(latencies)[int(len(latencies) * 0.99)], 3)
                    if len(latencies) > 1
                    else round(latencies[0], 3)
                ),
                "min_ms": round(min(latencies), 3),
                "max_ms": round(max(latencies), 3),
            }

        cache_total = self._cache_hits + self._cache_misses
        llm_free = sum(
            v for k, v in self._decision_sources.items() if k != "llm"
        ) if self._decision_sources else 0

        return {
            "total_readings": self._total_readings,
            "trust_score_distribution": {
                "mean": round(statistics.mean(self._trust_scores), 4) if self._trust_scores else None,
                "median": round(statistics.median(self._trust_scores), 4) if self._trust_scores else None,
                "stdev": round(statistics.stdev(self._trust_scores), 4) if len(self._trust_scores) > 1 else None,
                "min": round(min(self._trust_scores), 4) if self._trust_scores else None,
                "max": round(max(self._trust_scores), 4) if self._trust_scores else None,
            },
            "agent_latencies_ms": agent_stats,
            "scenario_distribution": dict(self._scenarios),
            "decision_distribution": dict(self._decisions),
            "action_distribution": dict(self._actions),
            "result_distribution": dict(self._results),
            "decision_source_distribution": dict(self._decision_sources),
            "llm_free_decision_pct": round((llm_free / self._total_readings) * 100, 1) if self._total_readings else 0.0,
            "cache": {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate": round(self._cache_hits / cache_total, 3) if cache_total > 0 else 0.0,
            },
            "degraded_mode_activations": self._degraded_activations,
        }

    def reset(self) -> None:
        """Clear all accumulated metrics for a fresh run."""
        self._agent_latencies.clear()
        self._trust_scores.clear()
        self._scenarios.clear()
        self._decisions.clear()
        self._actions.clear()
        self._results.clear()
        self._decision_sources.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._degraded_activations = 0
        self._total_readings = 0
