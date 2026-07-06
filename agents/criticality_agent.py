# Agent 5: Criticality Agent
# Classifies which agricultural scenario is happening
# LLM-powered - needs reasoning, not just rules
# This is where your friend's work connects

from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from pathlib import Path
import os
import json

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

CRITICALITY_PROMPT = """
You are an agricultural criticality detection agent on a farm fog server.
Given sensor readings, classify the situation into one of these scenarios:
1. Disease Outbreak
2. Heat Stress
3. Water Shortage
4. Soil Degradation
5. Excessive Rainfall
6. High Wind
7. Frost Risk
8. Sun Radiation Risk
9. Nutrient Deficiency
10. Pest Infestation
11. Normal (no critical scenario)

Respond ONLY with this JSON, nothing else:
{
    "critical": true or false,
    "scenario": "scenario name or Normal",
    "severity": "high or medium or low",
    "reasoning": "one sentence explanation"
}
"""

class CriticalityAgent:

    def __init__(self):
        self.llm = ChatGroq(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.1-8b-instant",
            temperature=0
        )

    def run(self, raw_readings: dict, tinyml_output: dict) -> dict:
        user_message = f"""
        Sensor readings:
        {json.dumps(raw_readings, indent=2)}

        TinyML output:
        {json.dumps(tinyml_output, indent=2)}

        Classify the agricultural scenario.
        Respond ONLY with JSON.
        """

        response = self.llm.invoke([
            SystemMessage(content=CRITICALITY_PROMPT),
            HumanMessage(content=user_message)
        ])

        raw = response.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            result = json.loads(raw)
            result["passed"] = True
            return result
        except json.JSONDecodeError:
            return {
                "passed": True,
                "critical": False,
                "scenario": "Normal",
                "severity": "low",
                "reasoning": "Failed to parse criticality response"
            }