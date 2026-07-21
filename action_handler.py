"""Enforcement Layer — Policy Enforcement Point (PEP) for the fog node.

Routes decisions based on trust level, enforces action whitelists,
and coordinates with the validation agent and cloud interface.

Dependencies are injected via constructor so the pipeline retains full
control over agent lifecycle and configuration.
"""

from __future__ import annotations

from actuator_adapters import ActuatorAdapter, build_actuator_adapter, make_command
from config import ACTION_WHITELIST
from cloud_interface import CloudInterface
from models import TrustLevel
from validation_agent import ValidationAgent


class ActionHandler:
    """Policy Enforcement Point for the fog decision loop.

    Args:
        validation_agent: Second-opinion validator for MEDIUM trust.
        cloud: Cloud interface for escalation and rejection notification.
    """

    def __init__(
        self,
        validation_agent: ValidationAgent | None = None,
        cloud: CloudInterface | None = None,
        actuator: ActuatorAdapter | None = None,
    ):
        self.validation_agent = validation_agent or ValidationAgent()
        self.cloud = cloud or CloudInterface()
        self.actuator = actuator or build_actuator_adapter()

    def route(
        self,
        action: str,
        decision: dict,
        trust_level: TrustLevel | str,
        context: dict | None = None,
    ) -> str:
        """Route a decision based on trust level.

        - HIGH   → execute locally (whitelist-gated)
        - MEDIUM → request validation → confirm or escalate
        - LOW    → reject and notify cloud
        """
        context = context or {}
        if context.get("critical"):
            cloud_result = self.cloud.escalate({**context, "decision": decision})
            return f"cloud_decided: {cloud_result.get('cloud_decision')}"
        if trust_level == TrustLevel.HIGH:
            return self.execute(action, context)
        if trust_level == TrustLevel.MEDIUM:
            return self.request_validation(decision, context)
        return self.reject_and_alert(
            decision.get("reasoning", "low trust"),
            context,
        )

    def execute(self, action: str, context: dict | None = None) -> str:
        """Execute a whitelisted action locally."""
        if action == "no_action":
            return "no_action_executed"
        if action not in ACTION_WHITELIST:
            return self.reject_and_alert(
                f"Blocked action '{action}' - not in whitelist"
            )
        print(f"[ACTION] Dispatching: {action}")
        return self.actuator.execute(make_command(action, context))

    def request_validation(
        self, decision: dict, context: dict | None = None
    ) -> str:
        """Request a second opinion from the validation agent."""
        context = context or {}
        print("[VALIDATION] Requesting second opinion...")
        verdict = self.validation_agent.validate(decision, context)
        print(
            f"[VALIDATION] Verdict: {verdict['verdict']} "
            f"(confidence: {verdict['confidence']}) "
            f"- {verdict['reasoning']}"
        )
        if verdict["verdict"] == "confirmed":
            return self.execute(decision.get("action_required", "no_action"), context)
        cloud_result = self.cloud.escalate({**context, "decision": decision})
        return f"cloud_decided: {cloud_result.get('cloud_decision')}"

    def reject_and_alert(
        self, reason: str, context: dict | None = None
    ) -> str:
        """Reject a decision and notify the cloud."""
        context = context or {}
        print(f"[REJECT] {reason}")
        self.cloud.notify_rejection(
            sensor_id=context.get("sensor_id", "unknown"),
            reason=reason,
        )
        return f"rejected: {reason}"
