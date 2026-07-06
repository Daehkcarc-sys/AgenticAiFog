# cloud_interface.py
# Simulates cloud layer responses when fog escalates
# In production this would use Apache Kafka (see architecture diagram)
# Topics: sensor-data, critical-events, trust-events, fog-decisions

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from pathlib import Path
import os
import json

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

CLOUD_PROMPT = """
You are a cloud intelligence agent in a smart farm global platform.
You receive escalated decisions from fog layer agents that couldn't act locally.
You have access to global context, historical data, and advanced ML models.

You must make a final decision with full authority.
Be specific about what action to take and why.

Respond ONLY with this JSON:
{
    "cloud_decision": "action to take",
    "reasoning": "one sentence with global context",
    "send_back_to_fog": true or false,
    "updated_policy": "any policy update to send back to fog"
}
"""

class CloudInterface:

    def __init__(self):
        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.1-8b-instant",
            temperature=0
        )

    def escalate(self, context: dict) -> dict:
        # simulate Kafka message to cloud
        print(f"[KAFKA] Publishing to 'fog-decisions' topic")
        print(f"[CLOUD] Global platform processing...")

        user_message = f"""
        Escalated decision from fog layer:
        
        Sensor: {context.get('sensor_id')}
        Trust Score: {context.get('trust_score')}
        Scenario: {context.get('scenario')}
        Critical: {context.get('critical')}
        Original Decision: {json.dumps(context.get('decision', {}), indent=2)}
        Raw Readings: {json.dumps(context.get('raw_readings', {}), indent=2)}
        
        Make a final cloud-level decision.
        Respond ONLY with JSON.
        """

        response = self.llm.invoke([
            SystemMessage(content=CLOUD_PROMPT),
            HumanMessage(content=user_message)
        ])

        raw = response.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            result = json.loads(raw)
            print(f"[CLOUD] Decision: {result.get('cloud_decision')}")
            print(f"[CLOUD] Reasoning: {result.get('reasoning')}")
            if result.get('send_back_to_fog'):
                print(f"[KAFKA] Publishing updated policy to 'policy-updates' topic")
            return result
        except json.JSONDecodeError:
            return {
                "cloud_decision": "manual_review",
                "reasoning": "Cloud parsing failed, flagging for human review",
                "send_back_to_fog": False,
                "updated_policy": None
            }

    def notify_rejection(self, sensor_id: str, reason: str) -> None:
        # called on Zero Trust rejections
        print(f"[KAFKA] Publishing rejection event to 'trust-events' topic")
        print(f"[CLOUD] Logging rejection for sensor {sensor_id}: {reason}")