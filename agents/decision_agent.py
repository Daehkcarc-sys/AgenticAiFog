# Agent 6: Decision Agent
# Final action decision based on full pipeline context
# LLM-powered - needs reasoning across all previous agent outputs

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from pathlib import Path
import os
import json

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

DECISION_PROMPT = """
You are the final decision agent in a smart farm fog layer pipeline.
You receive a complete picture of trust scores, sanity checks, and criticality assessment.
Your job is to make the final action decision.

Trust levels:
- 0.8-1.0: HIGH - Act Locally
- 0.5-0.8: MEDIUM - Ask Human / Validation Agent
- 0.0-0.5: LOW - Send to Cloud

Respond ONLY with this JSON, nothing else:
{
    "reasoning": "one sentence explanation",
    "decision": "act_locally or validate or escalate",
    "action_required": "irrigate or stop_irrigation or adjust_flow or trigger_alert or no_action or cloud or validation"
}
"""

class DecisionAgent:

    def __init__(self):
        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.1-8b-instant",
            temperature=0
        )

    def run(self, pipeline_context: dict) -> dict:
        user_message = f"""
        Complete pipeline context:
        
        Sensor ID: {pipeline_context.get('sensor_id')}
        Trust Score: {pipeline_context.get('trust_score')}
        Trust Level: {pipeline_context.get('trust_level')}
        Sanity Score: {pipeline_context.get('sanity_score')}
        Failed Fields: {pipeline_context.get('failed_fields', [])}
        Critical: {pipeline_context.get('critical')}
        Scenario: {pipeline_context.get('scenario')}
        Severity: {pipeline_context.get('severity')}
        TinyML Recommendation: {pipeline_context.get('tinyml_recommendation')}
        
        Make the final farm action decision.
        Respond ONLY with JSON.
        """

        response = self.llm.invoke([
            SystemMessage(content=DECISION_PROMPT),
            HumanMessage(content=user_message)
        ])

        raw = response.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "reasoning": "Failed to parse decision response",
                "decision": "escalate",
                "action_required": "cloud"
            }