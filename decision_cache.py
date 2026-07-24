"""Lightweight similarity-aware decision cache for the fog Intelligence Layer.

Avoids redundant LLM calls by reusing recent decisions when the current context
is similar enough to a cached entry. The cache stays stdlib-only and bounded for
fog nodes, but now behaves like the small local similarity-search index described
in the supervisor architecture instead of only doing exact hash reuse.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import CACHE_PATH


@dataclass
class CacheEntry:
    """A single cached decision with its compact searchable signature."""

    decision: dict[str, Any]
    signature: dict[str, Any]
    stored_at: float = field(default_factory=time.monotonic)
    hit_count: int = 0


class DecisionCache:
    """Bounded persistent cache with exact and similarity lookup.

    Lookup order:
    1. Exact key match on a normalized decision signature.
    2. Linear scan over cached signatures using a small weighted similarity
       score. This is intentionally dependency-free and suitable for small fog
       windows. A future vector store can replace this class without changing
       the public `lookup(context)` / `store(context, decision)` API.
    """

    def __init__(
        self,
        max_size: int = 64,
        ttl_seconds: float = 300.0,
        path: Path | None = CACHE_PATH,
        similarity_threshold: float = 0.82,
    ) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._similarity_threshold = similarity_threshold
        self._store: dict[str, CacheEntry] = {}
        self._insertion_order: list[str] = []
        self._hits: int = 0
        self._misses: int = 0
        self._similarity_hits: int = 0
        self._evictions: int = 0
        self._last_match: dict[str, Any] | None = None
        self._path = path
        self._load()

    def lookup(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Return a cached decision if the current context is close enough."""
        self._evict_expired()
        signature = self._make_signature(context)
        key = self._key_from_signature(signature)
        self._last_match = None

        exact = self._store.get(key)
        if exact is not None:
            exact.hit_count += 1
            self._hits += 1
            self._last_match = {
                "type": "exact",
                "score": 1.0,
                "key": key,
                "hit_count": exact.hit_count,
            }
            return {**exact.decision, "cache_similarity": 1.0, "cache_match_type": "exact"}

        best_key: str | None = None
        best_entry: CacheEntry | None = None
        best_score = 0.0
        for candidate_key, candidate in self._store.items():
            score = self._similarity(signature, candidate.signature)
            if score > best_score:
                best_key = candidate_key
                best_entry = candidate
                best_score = score

        if best_entry is not None and best_score >= self._similarity_threshold:
            best_entry.hit_count += 1
            self._hits += 1
            self._similarity_hits += 1
            self._last_match = {
                "type": "similarity",
                "score": round(best_score, 3),
                "key": best_key,
                "hit_count": best_entry.hit_count,
            }
            return {
                **best_entry.decision,
                "cache_similarity": round(best_score, 3),
                "cache_match_type": "similarity",
            }

        self._misses += 1
        self._last_match = {"type": "miss", "score": round(best_score, 3)}
        return None

    def store(self, context: dict[str, Any], decision: dict[str, Any]) -> None:
        """Persist a decision indexed by its normalized context signature."""
        self._evict_expired()
        signature = self._make_signature(context)
        key = self._key_from_signature(signature)

        if len(self._store) >= self._max_size and key not in self._store:
            old_key = self._insertion_order.pop(0)
            del self._store[old_key]
            self._evictions += 1

        self._store[key] = CacheEntry(decision=decision, signature=signature)
        if key not in self._insertion_order:
            self._insertion_order.append(key)
        self._persist()

    @property
    def stats(self) -> dict[str, Any]:
        """Return cache performance statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "similarity_hits": self._similarity_hits,
            "evictions": self._evictions,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            "ttl_seconds": self._ttl_seconds,
            "similarity_threshold": self._similarity_threshold,
            "last_match": self._last_match,
        }

    def reset(self) -> None:
        """Clear all cached entries and counters."""
        self._store.clear()
        self._insertion_order.clear()
        self._hits = 0
        self._misses = 0
        self._similarity_hits = 0
        self._evictions = 0
        self._last_match = None
        self._persist()

    @staticmethod
    def _make_signature(context: dict[str, Any]) -> dict[str, Any]:
        trust = float(context.get("trust_score", 0.0) or 0.0)
        raw_level = context.get("trust_level", "")
        level_str = raw_level.value if hasattr(raw_level, "value") else str(raw_level)
        anomalies = context.get("multi_level_anomalies", {}) or {}
        derived = context.get("derived_features", {}) or {}
        multimodal = context.get("multimodal_fusion", {}) or {}

        return {
            "trust_score": round(trust, 3),
            "trust_level": level_str,
            "scenario": str(context.get("scenario", "")),
            "severity": str(context.get("severity", "")),
            "critical": bool(context.get("critical", False)),
            "sanity_score": round(float(context.get("sanity_score", 1.0) or 0.0), 3),
            "tinyml_action": str(context.get("tinyml_recommendation", "")),
            "failed_fields": sorted(str(field) for field in context.get("failed_fields", [])),
            "anomaly_severity": str(anomalies.get("severity", "")),
            "anomaly_score": round(float(anomalies.get("score", 0.0) or 0.0), 3),
            "moisture_band": str(derived.get("soil_moisture_band", "")),
            "multimodal_risks": sorted(str(risk) for risk in multimodal.get("risk_indicators", [])),
        }

    @classmethod
    def _make_key(cls, context: dict[str, Any]) -> str:
        """Backward-compatible exact key helper used by older tests/callers."""
        return cls._key_from_signature(cls._make_signature(context))

    @staticmethod
    def _key_from_signature(signature: dict[str, Any]) -> str:
        exact_signature = {
            "trust_bucket": round(signature["trust_score"] / 0.05) * 0.05,
            "trust_level": signature["trust_level"],
            "scenario": signature["scenario"],
            "severity": signature["severity"],
            "critical": signature["critical"],
            "sanity_bucket": round(signature["sanity_score"] / 0.05) * 0.05,
            "tinyml_action": signature["tinyml_action"],
            "failed_fields": signature["failed_fields"],
            "anomaly_severity": signature["anomaly_severity"],
            "moisture_band": signature["moisture_band"],
            "multimodal_risks": signature["multimodal_risks"],
        }
        raw = json.dumps(exact_signature, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _similarity(current: dict[str, Any], cached: dict[str, Any]) -> float:
        score = 0.0
        total = 0.0

        def add(weight: float, value: float) -> None:
            nonlocal score, total
            score += weight * max(0.0, min(1.0, value))
            total += weight

        add(0.12, 1.0 if current["trust_level"] == cached["trust_level"] else 0.0)
        add(0.16, 1.0 if current["scenario"] == cached["scenario"] else 0.0)
        add(0.10, 1.0 if current["severity"] == cached["severity"] else 0.0)
        add(0.10, 1.0 if current["critical"] == cached["critical"] else 0.0)
        add(0.12, 1.0 if current["tinyml_action"] == cached["tinyml_action"] else 0.0)
        add(0.08, 1.0 if current["anomaly_severity"] == cached["anomaly_severity"] else 0.0)
        add(0.06, 1.0 if current["moisture_band"] == cached["moisture_band"] else 0.0)
        add(0.10, 1.0 - min(abs(current["trust_score"] - cached["trust_score"]) / 0.3, 1.0))
        add(0.08, 1.0 - min(abs(current["sanity_score"] - cached["sanity_score"]) / 0.3, 1.0))
        add(0.04, 1.0 - min(abs(current["anomaly_score"] - cached["anomaly_score"]) / 0.5, 1.0))
        add(0.02, DecisionCache._jaccard(current["failed_fields"], cached["failed_fields"]))
        add(0.02, DecisionCache._jaccard(current["multimodal_risks"], cached["multimodal_risks"]))
        return score / total if total else 0.0

    @staticmethod
    def _jaccard(left: list[str], right: list[str]) -> float:
        left_set = set(left)
        right_set = set(right)
        if not left_set and not right_set:
            return 1.0
        if not left_set or not right_set:
            return 0.0
        return len(left_set & right_set) / len(left_set | right_set)

    def _evict_expired(self) -> None:
        if self._ttl_seconds <= 0:
            return
        now = time.monotonic()
        expired = [
            key for key, entry in self._store.items()
            if now - entry.stored_at > self._ttl_seconds
        ]
        for key in expired:
            del self._store[key]
            if key in self._insertion_order:
                self._insertion_order.remove(key)
        if expired:
            self._persist()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._store = {}
            for key, value in data.get("store", {}).items():
                decision = value["decision"]
                signature = value.get("signature")
                if signature is None:
                    signature = self._make_signature(value.get("context", {}))
                self._store[key] = CacheEntry(
                    decision=decision,
                    signature=signature,
                    stored_at=value["stored_at"],
                    hit_count=value.get("hit_count", 0),
                )
            self._insertion_order = data.get("insertion_order", list(self._store))
        except (json.JSONDecodeError, KeyError, TypeError):
            self._store = {}
            self._insertion_order = []

    def _persist(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "store": {
                key: {
                    "decision": entry.decision,
                    "signature": entry.signature,
                    "stored_at": entry.stored_at,
                    "hit_count": entry.hit_count,
                }
                for key, entry in self._store.items()
            },
            "insertion_order": self._insertion_order,
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
