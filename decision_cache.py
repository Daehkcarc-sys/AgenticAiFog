"""Lightweight semantic similarity cache for fog Intelligence Layer.

Avoids redundant LLM calls by reusing recent decisions when the current
context falls into the same *semantic bucket* as a cached entry.  Rather
than performing expensive vector similarity search, continuous features
are discretized into coarse buckets (LOW/MEDIUM/HIGH) so that O(1) dict
lookup suffices.

Designed for constrained Fog nodes (Industrial PC, NVIDIA Jetson, server-
class gateway).  No external dependencies, bounded memory, configurable
TTL and eviction policy.

Trade-offs vs. exact matching:
  - PRO: higher hit rate — similar-but-not-identical contexts match.
  - PRO: O(1) lookup via dict key, no ANN index needed.
  - CON: possible false positives — different contexts may map to the
    same bucket.  Mitigated by the ActionHandler PEP which enforces
    the action whitelist regardless of cache output.
  - CON: bucket boundaries are fixed — tuning requires code changes.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

# ── Semantic bucket thresholds ──────────────────────────────


def _bucket_trust(score: float) -> str:
    """Discretize trust score into 0.05 buckets → ~20 possible values."""
    return f"{round(score / 0.05) * 0.05:.2f}"


def _bucket_sanity(score: float) -> str:
    """Discretize sanity score into 3 semantic buckets."""
    if score >= 0.9:
        return "HIGH"       # all or nearly all fields OK
    if score >= 0.5:
        return "MEDIUM"     # some fields out of range
    return "LOW"            # most fields suspect


def _resolve_level(raw: Any) -> str:
    """Resolve trust_level enum or string to canonical string."""
    return raw.value if hasattr(raw, "value") else str(raw)


# ── Cache data structures ───────────────────────────────────


@dataclass
class CacheEntry:
    """A single cached decision with metadata."""

    decision: dict[str, Any]
    stored_at: float = field(default_factory=time.monotonic)
    hit_count: int = 0


class DecisionCache:
    """Semantic similarity cache for fog-layer decisions.

    Each context is reduced to a *semantic signature* by bucketing
    continuous features and keeping categorical features as-is.  Two
    contexts that produce the same signature are considered similar
    enough to share a decision.

    Design constraints for Fog nodes:
    - O(1) dict lookup (no ANN, no vector DB)
    - Bounded memory (configurable ``max_size``, FIFO eviction)
    - Configurable TTL for stale entry expiration
    - No external dependencies
    """

    def __init__(
        self,
        max_size: int = 64,
        ttl_seconds: float = 300.0,
    ) -> None:
        """
        Args:
            max_size: Maximum cached entries (FIFO eviction when full).
            ttl_seconds: Entries older than this are considered stale.
                         Set to 0 to disable TTL eviction.
        """
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, CacheEntry] = {}
        self._insertion_order: list[str] = []  # FIFO queue
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    # ── public API ──────────────────────────────────────────

    def lookup(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Return a cached decision for a semantically similar context, or None.

        The *context* is reduced to a semantic signature (bucketed trust,
        bucketed sanity, categorical scenario/severity/action).  If a
        matching signature exists and has not expired, its decision is
        returned and the hit counter incremented.
        """
        self._evict_expired()
        key = self._make_key(context)

        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        entry.hit_count += 1
        self._hits += 1
        return entry.decision

    def store(self, context: dict[str, Any], decision: dict[str, Any]) -> None:
        """Persist a decision indexed by its semantic signature."""
        self._evict_expired()
        key = self._make_key(context)

        # FIFO eviction when at capacity and adding a new key
        if len(self._store) >= self._max_size and key not in self._store:
            old_key = self._insertion_order.pop(0)
            del self._store[old_key]
            self._evictions += 1

        self._store[key] = CacheEntry(decision=decision)
        if key not in self._insertion_order:
            self._insertion_order.append(key)

    @property
    def stats(self) -> dict[str, Any]:
        """Return cache performance statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            "ttl_seconds": self._ttl_seconds,
        }

    def reset(self) -> None:
        """Clear all cached entries and counters."""
        self._store.clear()
        self._insertion_order.clear()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    # ── internals ───────────────────────────────────────────

    @staticmethod
    def _make_key(context: dict[str, Any]) -> str:
        """Build a semantic signature key from the decision context.

        Continuous features are discretized into coarse buckets so that
        similar-but-not-identical readings map to the same key.  Only
        features that affect decision-making are included.

        Bucketing strategy:
        - trust_score  → 0.05 buckets (~20 possible values)
        - sanity_score → LOW / MEDIUM / HIGH (3 buckets)
        - scenario, severity, tinyml_action → kept as-is (categorical)
        - critical → boolean
        - trust_level → canonical string (HIGH / MEDIUM / LOW)
        """
        signature = {
            "t": _bucket_trust(context.get("trust_score", 0.0)),
            "tl": _resolve_level(context.get("trust_level", "")),
            "s": _bucket_sanity(context.get("sanity_score", 1.0)),
            "sc": context.get("scenario", ""),
            "sv": context.get("severity", ""),
            "cr": context.get("critical", False),
            "ta": context.get("tinyml_recommendation", ""),
        }
        return json.dumps(signature, sort_keys=True)

    def _evict_expired(self) -> None:
        """Remove entries older than ``_ttl_seconds``."""
        if self._ttl_seconds <= 0:
            return
        now = time.monotonic()
        expired = [
            k
            for k, v in self._store.items()
            if now - v.stored_at > self._ttl_seconds
        ]
        for k in expired:
            del self._store[k]
            if k in self._insertion_order:
                self._insertion_order.remove(k)
