from __future__ import annotations

from config import ACTION_WHITELIST
from cloud_interface import CloudInterface
from models import TrustLevel
from validation_agent import ValidationAgent


class ActionHandler:
    """Policy Enforcement Point for the fog decision loop."""

    def __init__(self):
        self.validation_agent = ValidationAgent()
        self.cloud = CloudInterface()

    def route(self, action: str, decision: dict, trust_level: TrustLevel | str, context: dict | None = None) -> str:
        context = context or {}
        if trust_level == TrustLevel.HIGH:
            return self.execute(action)
        if trust_level == TrustLevel.MEDIUM:
            return self.request_validation(decision, context)

        return self.reject_and_alert(
            decision.get("reasoning", "low trust"),
            context,
        )

    def execute(self, action: str) -> str:
        if action not in ACTION_WHITELIST:
            return self.reject_and_alert(
                f"Blocked action '{action}' - not in whitelist"
            )

        print(f"[ACTION] Executing: {action}")
        return f"{action}_executed"

    def request_validation(self, decision: dict, context: dict | None = None) -> str:
        context = context or {}
        print("[VALIDATION] Requesting second opinion...")
        verdict = self.validation_agent.validate(decision, context)
        print(
            f"[VALIDATION] Verdict: {verdict['verdict']} "
            f"(confidence: {verdict['confidence']}) "
            f"- {verdict['reasoning']}"
        )

        if verdict["verdict"] == "confirmed":
            return self.execute(decision.get("action_required", "no_action"))

        cloud_result = self.cloud.escalate({**context, "decision": decision})
        return f"cloud_decided: {cloud_result.get('cloud_decision')}"

    def reject_and_alert(self, reason: str, context: dict | None = None) -> str:
        context = context or {}
        print(f"[REJECT] {reason}")
        self.cloud.notify_rejection(
            sensor_id=context.get("sensor_id", "unknown"),
            reason=reason,
        )
        return f"rejected: {reason}"

