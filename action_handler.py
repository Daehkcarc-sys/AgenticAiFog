# action_handler.py
from validation_agent import ValidationAgent
from cloud_interface import CloudInterface

ALLOWED_ACTIONS = [
    "irrigate", "stop_irrigation",
    "adjust_flow", "trigger_alert", "no_action"
]

class ActionHandler:

    def __init__(self):
        self.validation_agent = ValidationAgent()
        self.cloud = CloudInterface()

    def route(self, action: str, decision: dict,
              trust_level: str, context: dict = {}) -> str:
        if trust_level == "HIGH":
            return self.execute(action)
        elif trust_level == "MEDIUM":
            return self.request_validation(decision, context)
        else:
            return self.reject_and_alert(
                decision.get("reasoning", "low trust"),
                context
            )

    def execute(self, action: str) -> str:
        if action not in ALLOWED_ACTIONS:
            return self.reject_and_alert(
                f"Blocked action '{action}' - not in whitelist"
            )
        print(f"[ACTION] Executing: {action}")
        return f"{action}_executed"

    def request_validation(self, decision: dict, context: dict = {}) -> str:
        print(f"[VALIDATION] Requesting second opinion...")
        verdict = self.validation_agent.validate(decision, context)
        print(f"[VALIDATION] Verdict: {verdict['verdict']} "
              f"(confidence: {verdict['confidence']}) "
              f"- {verdict['reasoning']}")

        if verdict["verdict"] == "confirmed":
            return self.execute(decision.get("action_required", "no_action"))

        # escalate to cloud
        cloud_result = self.cloud.escalate({
            **context,
            "decision": decision
        })
        return f"cloud_decided: {cloud_result.get('cloud_decision')}"

    def reject_and_alert(self, reason: str, context: dict = {}) -> str:
        print(f"[REJECT] {reason}")
        self.cloud.notify_rejection(
            sensor_id=context.get("sensor_id", "unknown"),
            reason=reason
        )
        return f"rejected: {reason}"