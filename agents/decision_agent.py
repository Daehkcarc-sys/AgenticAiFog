"""Intelligence Layer — hierarchical fog decision agent.

Decision flow (cheapest → most expensive):
  1. Deterministic rules  → returns immediately (no I/O)
  2. Decision cache       → reuses recent similar decisions
  3. LLM reasoning        → only invoked when rules + cache miss
  4. Cloud escalation     → fallback on LLM failure

Each decision records its ``source`` so the pipeline can measure
how often each tier was used.
"""

from __future__ import annotations

from typing import Any

from config import LOCAL_ACTION_MIN_SANITY_SCORE
from decision_cache import DecisionCache
from llm_factory import safe_invoke
from models import DecisionResult, TrustLevel

# ── Deterministic rule definitions ─────────────────────────

# When trust is HIGH and the TinyML recommendation is a simple farm
# action, we can skip the LLM entirely.
_HIGH_TRUST_ACTIONS: frozenset[str] = frozenset(
    {"irrigate", "stop_irrigation", "adjust_flow", "trigger_alert", "no_action"}
)


DECISION_PROMPT = """
You are the final decision agent in a smart farm fog layer pipeline.
You receive a complete picture of trust scores, sanity checks, and criticality assessment.
Your job is to make the final action decision.

Trust levels:
- 0.8-1.0: HIGH - Act Locally
- 0.5-0.8: MEDIUM - Ask Human / Validation Agent
- 0.0-0.5: LOW - Send to Cloud

Before deciding, consider:
- Does the recommended action match the sensor readings?
- Is the criticality scenario consistent with the data?
- Are any sensor fields outside their valid range?
- Would a wrong decision cause crop damage?

Respond ONLY with this JSON, nothing else:
{
    "reasoning": "one sentence explaining why this action was chosen",
    "decision": "act_locally or validate or escalate",
    "action_required": "irrigate or stop_irrigation or adjust_flow or trigger_alert or no_action or cloud or validation"
}
"""

DECISION_FALLBACK: dict[str, str] = {
    "reasoning": "LLM unavailable - escalating to cloud for safety",
    "decision": "escalate",
    "action_required": "cloud",
}


class DecisionAgent:
    """Hierarchical fog decision maker.

    Consumes trust results, context, criticality, and policies to
    produce a ``DecisionResult``.  Only invokes the LLM when simpler
    resolution strategies are exhausted.

    Args:
        cache: Optional ``DecisionCache`` for reusing recent decisions.
    """

    def __init__(self, cache: DecisionCache | None = None):
        self._cache = cache

    def run(self, pipeline_context: dict[str, Any]) -> DecisionResult:
        # ── Tier 1: deterministic rules ─────────────────
        rule_result = self._try_rules(pipeline_context)
        if rule_result is not None:
            return rule_result

        # ── Tier 2: decision cache ──────────────────────
        if self._cache is not None:
            cached = self._cache.lookup(pipeline_context)
            if cached is not None:
                return DecisionResult(
                    reasoning=cached.get("reasoning", "cached decision"),
                    decision=cached.get("decision", "escalate"),
                    action_required=cached.get("action_required", "cloud"),
                    source="cache",
                )

        # ── Tier 3: LLM reasoning ───────────────────────
        llm_result = self._invoke_llm(pipeline_context)

        # ── Store in cache for future reuse ─────────────
        if self._cache is not None:
            self._cache.store(pipeline_context, llm_result.to_dict())

        return llm_result

    # ── private helpers ────────────────────────────────────

    @staticmethod
    def _try_rules(
        pipeline_context: dict[str, Any],
    ) -> DecisionResult | None:
        """Attempt deterministic resolution.  Returns None if no rule matches."""
        trust_level = pipeline_context.get("trust_level", TrustLevel.LOW)
        tinyml_action = str(pipeline_context.get("tinyml_recommendation", ""))
        critical = bool(pipeline_context.get("critical", False))
        sanity_score = float(pipeline_context.get("sanity_score", 0.0))
        failed_fields = pipeline_context.get("failed_fields", [])
        policy_allowed = bool(pipeline_context.get("policy_allowed", False))

        # HIGH trust + simple action → act locally
        if (
            trust_level in (TrustLevel.HIGH, "HIGH")
            and tinyml_action in _HIGH_TRUST_ACTIONS
            and not critical
            and sanity_score >= LOCAL_ACTION_MIN_SANITY_SCORE
            and not failed_fields
            and policy_allowed
        ):
            return DecisionResult(
                reasoning=(
                    f"High trust with straightforward action "
                    f"'{tinyml_action}' — acting locally"
                ),
                decision="act_locally",
                action_required=tinyml_action,
                source="rule",
            )

        # LOW trust → always reject (ActionHandler enforces this)
        if trust_level in (TrustLevel.LOW, "LOW"):
            return DecisionResult(
                reasoning=(
                    "Low trust score — rejecting to protect farm operations"
                ),
                decision="reject",
                action_required="cloud",
                source="rule",
            )

        return None  # MEDIUM or complex HIGH → try cache / LLM

    @staticmethod
    def _invoke_llm(pipeline_context: dict[str, Any]) -> DecisionResult:
        # Resolve trust_level to its string value for the LLM prompt
        raw_level = pipeline_context.get("trust_level", "")
        level_str = raw_level.value if hasattr(raw_level, "value") else str(raw_level)

        user_message = (
            f"Complete pipeline context:\n\n"
            f"Sensor ID: {pipeline_context.get('sensor_id')}\n"
            f"Trust Score: {pipeline_context.get('trust_score')}\n"
            f"Trust Level: {level_str}\n"
            f"Sanity Score: {pipeline_context.get('sanity_score')}\n"
            f"Failed Fields: {pipeline_context.get('failed_fields', [])}\n"
            f"Critical: {pipeline_context.get('critical')}\n"
            f"Scenario: {pipeline_context.get('scenario')}\n"
            f"Severity: {pipeline_context.get('severity')}\n"
            f"TinyML Recommendation: {pipeline_context.get('tinyml_recommendation')}\n\n"
            f"Make the final farm action decision.\n"
            f"Respond ONLY with JSON."
        )
        result = safe_invoke(DECISION_PROMPT, user_message, DECISION_FALLBACK)
        return DecisionResult(
            reasoning=result.get("reasoning", DECISION_FALLBACK["reasoning"]),
            decision=result.get("decision", DECISION_FALLBACK["decision"]),
            action_required=result.get(
                "action_required", DECISION_FALLBACK["action_required"]
            ),
            source="fallback" if result.get("_fallback_used") else "llm",
        )
