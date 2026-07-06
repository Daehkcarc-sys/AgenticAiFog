# validation_agent.py
# Second opinion agent for MEDIUM trust decisions
# Called when trust score is 0.5-0.8
# LLM-powered - needs to reason about whether to confirm or escalate

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from pathlib import Path
import os
import json

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

VALIDATION_PROMPT = """
You are a validation agent in a smart farm fog layer pipeline.
Your job is to give a second opinion on decisions made by the main fog agent.
You are called only when trust is MEDIUM (0.5-0.8) - not high enough to act alone.

You must be conservative - when in doubt, escalate to cloud.
A wrong irrigation decision can damage crops.

Consider:
- Does the recommended action make sense given the sensor readings?
- Is the criticality scenario consistent with the data?
- Is the trust score high enough for this specific action?

Respond ONLY with this JSON, nothing else:
{
    "verdict": "confirmed or escalate",
    "confidence": 0.0 to 1.0,
    "reasoning": "one sentence explanation"
}
"""

class ValidationAgent:

    def __init__(self):
        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.1-8b-instant",
            temperature=0
        )

    def validate(self, decision: dict, context: dict = {}) -> dict:
        user_message = f"""
        Main agent decision to validate:
        {json.dumps(decision, indent=2)}

        Pipeline context:
        - Trust Score: {context.get('trust_score', 'unknown')}
        - Scenario: {context.get('scenario', 'unknown')}
        - Critical: {context.get('critical', False)}
        - Sanity Score: {context.get('sanity_score', 'unknown')}
        - Raw Readings Summary: {json.dumps(context.get('raw_readings', {}), indent=2)}

        Should this decision be confirmed or escalated to cloud?
        Respond ONLY with JSON.
        """

        response = self.llm.invoke([
            SystemMessage(content=VALIDATION_PROMPT),
            HumanMessage(content=user_message)
        ])

        raw = response.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # safe fallback - escalate if unsure
            return {
                "verdict": "escalate",
                "confidence": 0.0,
                "reasoning": "Failed to parse validation response - escalating to be safe"
            }