"""Lightweight decision cache for the fog Intelligence Layer.

Avoids redundant LLM calls by reusing recent decisions when the current
context is similar enough to a cached entry.  Designed for constrained
Fog nodes (Raspberry Pi, Jetson Nano, industrial gateways).

Usage::

    cache = DecisionCache(max_size=64, similarity_threshold=0.90)
    cached = cache.lookup(trust_score=0.95, scenario="Water deficit", ...)
    if cached:
        return cached  # cache hit — no LLM needed
    result = llm_decision(...)
    cache.store(signature, result)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    """A single cached decision with metadata."""

    decision: dict[str, Any]
    stored_at: float = field(default_factory=time.monotonic)
    hit_count: int = 0


class DecisionCache:
    """Bounded in-memory cache for fog-layer decisions.

    Keys are derived from a hash of the decision context.  When a lookup
    is requested the cache checks whether the current context is *similar
    enough* to any cached entry by comparing discretized trust scores,
    scenario labels, and sensor health indicators.

    Design constraints for Fog nodes:
    - Bounded memory (configurable ``max_size``)
    - O(1) lookup via dict key
    - No external dependencies
    - Optional TTL for stale entry eviction
    """

    def __init__(
        self,
        max_size: int = 64,
        ttl_seconds: float = 300.0,
    ) -> None:
        """
        Args:
            max_size: Maximum number of cached entries (FIFO eviction).
            ttl_seconds: Entries older than this are considered stale.
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
        """Return a cached decision if one matches *context*, else None.

        The context is hashed to produce a lookup key.  If a matching
        entry exists and has not expired, it is returned and its hit
        counter incremented.
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
        """Persist a decision indexed by its context."""
        self._evict_expired()
        key = self._make_key(context)

        # Evict oldest if at capacity (FIFO)
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
        self._evictions = 0
        self._misses = 0

    # ── internals ───────────────────────────────────────────

    @staticmethod
    def _make_key(context: dict[str, Any]) -> str:
        """Produce a stable hash key from the decision context.

        Only the fields that affect decision-making are hashed so that
        minor variations (e.g. raw_readings timestamps) don't cause
        unnecessary cache misses.
        """
        # Discretize trust score into 0.05 buckets to increase hit rate
        trust = context.get("trust_score", 0.0)
        trust_bucket = round(trust / 0.05) * 0.05

        # Resolve trust_level to its string value (handles enum members)
        raw_level = context.get("trust_level", "")
        level_str = raw_level.value if hasattr(raw_level, "value") else str(raw_level)

        signature = {
            "trust_bucket": trust_bucket,
            "trust_level": level_str,
            "scenario": context.get("scenario", ""),
            "severity": context.get("severity", ""),
            "critical": context.get("critical", False),
            "sanity_score": round(context.get("sanity_score", 1.0), 2),
            "tinyml_action": context.get("tinyml_recommendation", ""),
        }

        raw = json.dumps(signature, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

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
