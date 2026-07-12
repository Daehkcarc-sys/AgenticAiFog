from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List


class TrustLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DecisionMode(str, Enum):
    ACT_LOCALLY = "act_locally"
    VALIDATE = "validate"
    ESCALATE = "escalate"
    REJECT = "reject"


class ActionRequired(str, Enum):
    IRRIGATE = "irrigate"
    STOP_IRRIGATION = "stop_irrigation"
    ADJUST_FLOW = "adjust_flow"
    TRIGGER_ALERT = "trigger_alert"
    NO_ACTION = "no_action"
    CLOUD = "cloud"
    VALIDATION = "validation"


class CriticalityScenario(str, Enum):
    NORMAL = "Normal"
    WATER_DEFICIT = "Water deficit"
    FLOODING = "Flooding"
    HEAT_STRESS = "Fire or heat stress"
    DISEASE_RISK = "Crop disease risk"
    PEST_INFESTATION = "Pest infestation risk"
    SOIL_DEGRADATION = "Soil degradation"
    EQUIPMENT_FAILURE = "Equipment failure"


# ── Structured Agent Results ──────────────────────────────────


class FogAgentResult:
    """Base for structured agent outputs with dict-like backward compat.

    Subclasses are ``@dataclass`` types that support both attribute
    access (``result.passed``) and dict-style access (``result["passed"]``)
    so existing pipeline code continues to work unchanged.
    """

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult(FogAgentResult):
    """Output of DataValidationAgent."""
    passed: bool
    reason: str


@dataclass
class TimestampResult(FogAgentResult):
    """Output of TimestampAgent."""
    passed: bool
    freshness_score: float
    reason: str
    age_seconds: float = 0.0


@dataclass
class TrustScoreResult(FogAgentResult):
    """Output of TrustScoreAgent."""
    passed: bool
    trust_score: float
    consistency_score: float
    reason: str


@dataclass
class SanityResult(FogAgentResult):
    """Output of ValueSanityAgent."""
    passed: bool
    sanity_score: float
    failed_fields: list[str]
    reason: str


@dataclass
class CriticalityResult(FogAgentResult):
    """Output of CriticalityAgent."""
    passed: bool
    critical: bool
    scenario: str
    severity: str
    reasoning: str


@dataclass
class DecisionResult(FogAgentResult):
    """Output of DecisionAgent."""
    reasoning: str
    decision: str
    action_required: str
    source: str = "llm"  # "rule" | "cache" | "llm" | "cloud"


# ── Data Models ───────────────────────────────────────────────


@dataclass
class TinyMLOutput:
    recommended_action: str
    confidence: float
    anomaly_detected: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_action": self.recommended_action,
            "confidence": self.confidence,
            "anomaly_detected": self.anomaly_detected,
            **self.extra,
        }


@dataclass
class SensorMessage:
    sensor_id: str
    timestamp: str
    raw_readings: Dict[str, Any]
    tinyml_output: TinyMLOutput
    scenario: str = "normal"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "timestamp": self.timestamp,
            "raw_readings": self.raw_readings,
            "tinyml_output": self.tinyml_output.to_dict(),
            "scenario": self.scenario,
        }


@dataclass
class LogEntry:
    sensor_id: str
    trust_score: float
    trust_level: TrustLevel
    decision: Dict[str, Any]
    result: str
    scenario: str = "N/A"
    critical: bool = False
    additional: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "logged_at": self.additional.get("logged_at"),
            "sensor_id": self.sensor_id,
            "trust_score": self.trust_score,
            "trust_level": self.trust_level.value if isinstance(self.trust_level, TrustLevel) else self.trust_level,
            "scenario": self.scenario,
            "critical": self.critical,
            "decision": self.decision,
            "result": self.result,
            **{k: v for k, v in self.additional.items() if k != "logged_at"},
        }
