"""Typed contracts for inter-agent communication in the fog pipeline.

Each ``TypedDict`` defines the output shape of one pipeline agent.
These are zero-overhead at runtime (plain ``dict``) but provide
full static analysis support for type-checkers and IDEs.

Usage::

    from contracts import ValidationResult, TrustScoreResult

    def consume(result: ValidationResult) -> None:
        if result["passed"]:        # IDE autocompletes "passed"
            ...
"""

from __future__ import annotations

from typing import TypedDict


class ValidationResult(TypedDict):
    """Output of ``DataValidationAgent.run()``."""
    passed: bool
    reason: str


class TimestampResult(TypedDict):
    """Output of ``TimestampAgent.run()``."""
    passed: bool
    freshness_score: float
    reason: str
    age_seconds: float  # present only when passed=True


class TrustScoreResult(TypedDict):
    """Output of ``TrustScoreAgent.run()``."""
    passed: bool
    trust_score: float
    consistency_score: float
    reason: str


class SanityResult(TypedDict):
    """Output of ``ValueSanityAgent.run()``."""
    passed: bool
    sanity_score: float
    failed_fields: list[str]
    reason: str


class CriticalityResult(TypedDict):
    """Output of ``CriticalityAgent.run()``."""
    passed: bool
    critical: bool
    scenario: str
    severity: str  # "high" | "medium" | "low"
    reasoning: str


class DecisionResult(TypedDict):
    """Output of ``DecisionAgent.run()``."""
    reasoning: str
    decision: str  # "act_locally" | "validate" | "escalate" | "reject"
    action_required: str  # "irrigate" | "stop_irrigation" | ...


class ValidationVerdict(TypedDict):
    """Output of ``ValidationAgent.validate()``."""
    verdict: str  # "confirmed" | "escalate"
    confidence: float
    reasoning: str


class CloudDecision(TypedDict):
    """Output of ``CloudInterface.escalate()``."""
    cloud_decision: str
    reasoning: str
    send_back_to_fog: bool
    updated_policy: str | None


class PipelineContext(TypedDict, total=False):
    """Context dict passed between pipeline stages and to ``ActionHandler``."""
    sensor_id: str
    trust_score: float
    trust_level: str
    sanity_score: float
    failed_fields: list[str]
    critical: bool
    scenario: str
    severity: str
    tinyml_recommendation: str | None
    raw_readings: dict
    decision: dict
