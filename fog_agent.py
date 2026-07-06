# fog_agent.py
# Main fog layer agent - receives TinyML output, reasons, decides
# Uses TrustScorer as gatekeeper before any decision is made

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from trust_scorer import TrustScorer
from action_handler import ActionHandler
from dotenv import load_dotenv
import os
import json
from pathlib import Path
from logger import FogLogger

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
#Bro is allergic to JSON
SYSTEM_PROMPT = """
You are a fog layer agent managing a smart farm IoT system.
You receive pre-processed sensor data and TinyML recommendations from edge devices.
Your job is to decide one of four actions based on the trust score provided:
- HIGH trust (>0.8): execute the recommended action locally
- MEDIUM trust (0.6-0.8): consult the validation agent before acting
- LOW trust (<0.6): reject the data, trigger alert, notify cloud
You must always explain your reasoning briefly before stating your final decision.
YOU MUST respond with ONLY a JSON object, no other text, no explanation outside the JSON.
Format:
{{
    "reasoning": "brief explanation",
    "decision": "act_locally or validate or escalate or reject",
    "action_required": "irrigate or stop_irrigation or adjust_flow or trigger_alert or no_action or cloud or validation"
}}
"""


class FogAgent:

    def __init__(self):
        # llama-3.1-8b-instant: speed over power, fog layer needs fast decisions
        # temperature=0 means deterministic responses - no randomness in farm decisions
        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.1-8b-instant",
            temperature=0
        )
        self.trust_scorer = TrustScorer()
        self.action_handler = ActionHandler()
        self.logger=FogLogger()


    def perceive(self, sensor_data: dict) -> dict:

        score = self.trust_scorer.score(sensor_data)
        level = self.trust_scorer.get_trust_level(score)
        print(f"[TRUST] Score: {score} | Level: {level}")
        return {
            **sensor_data,
            "trust_score": score,
            "trust_level": level
        }

    def reason(self, enriched_data: dict) -> dict:
        # build a human readable summary of the situation for the LLM
        user_message = f"""
        You are receiving a sensor reading. You MUST respond with ONLY a JSON object, nothing else.

        Sensor ID: {enriched_data.get('sensor_id')}
        Timestamp: {enriched_data.get('timestamp')}
        Raw Readings: {json.dumps(enriched_data.get('raw_readings', {}), indent=2)}
        TinyML Output: {json.dumps(enriched_data.get('tinyml_output', {}), indent=2)}
        Trust Score: {enriched_data.get('trust_score')}
        Trust Level: {enriched_data.get('trust_level')}

        Rules:
        - If Trust Level is HIGH: action_required must be a farm action like irrigate or no_action
        - If Trust Level is MEDIUM: action_required must be "validation"
        - If Trust Level is LOW: action_required must be "cloud"

        Respond with ONLY this JSON, no text before or after:
        {{
            "reasoning": "one sentence explanation",
            "decision": "act_locally or validate or escalate or reject",
            "action_required": "irrigate or stop_irrigation or no_action or validation or cloud"
        }}
        """

        response = self.llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_message)
        ])

        # strip markdown fences if LLM wraps response in ```json
        raw = response.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # if LLM doesn't return valid JSON, safe fallback
            return {
                "reasoning": "Failed to parse LLM response",
                "decision": "escalate",
                "action_required": "cloud"
            }

    def act(self, decision: dict, trust_level: str) -> str:
        # trust level is the gatekeeper, LLM decision is the detail
        if trust_level == "HIGH":
            action = decision.get("action_required", "no_action")
            return self.action_handler.execute(action)

        elif trust_level == "MEDIUM":
            # forward to validation agent (friend's agent)
            # for now we simulate this
            return self.action_handler.request_validation(decision)

        else:
            # LOW trust - reject, alert, notify cloud
            return self.action_handler.reject_and_alert(
                reason=decision.get("reasoning", "low trust score")
            )

    def run(self, sensor_data: dict) -> str:
        enriched = self.perceive(sensor_data)

        if enriched["trust_score"] == 0.0:
            result = self.action_handler.reject_and_alert(
                reason="Unknown sensor identity - Zero Trust rejection"
            )
            self.logger.log(
                sensor_id=sensor_data.get("sensor_id"),
                trust_score=0.0,
                trust_level="LOW",
                decision={"reasoning": "Unknown sensor identity"},
                result=result
            )
            return result

        decision = self.reason(enriched)
        result = self.act(decision, enriched["trust_level"])
        
        self.logger.log(
            sensor_id=sensor_data.get("sensor_id"),
            trust_score=enriched["trust_score"],
            trust_level=enriched["trust_level"],
            decision=decision,
            result=result
        )
        
        return result