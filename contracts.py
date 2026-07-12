"""Typed contracts for fog pipeline communication.

TypedDicts document the shape of dicts that flow between pipeline
components.  Agent outputs now use structured dataclasses from
``models.py`` — these TypedDicts cover only the remaining dict-based
interfaces (pipeline context, validation verdicts, cloud decisions).
"""

from __future__ import annotations

from typing import TypedDict


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
