# Fog Layer Agentic AI — Smart Farm Digital Twin

## Overview

A trust-oriented multi-agent pipeline running on the fog layer of an agricultural IoT system.
Implements Zero Trust security principles for real-time sensor data validation and decision making.

Based on the Cloud-Fog-Edge Agricultural Digital Twin Architecture with a 6-agent pipeline
mapped directly to the supervisor's architecture diagram.

---

## System Architecture

```
EDGE LAYER
├── Soil sensors, water actuators, smart machinery
└── TinyML model → criticality flag + confidence score
                        ↓ LoRa / LoRaWAN

FOG LAYER  (this project)
└── 6-Agent Pipeline
    │
    ├── Agent 1: Data Validation     → identity, format, required fields
    ├── Agent 2: Timestamp           → freshness, replay attack detection
    ├── Agent 3: Trust Score         → early exit gate (Zero Trust)
    ├── Agent 4: Value Sanity        → physical range validation
    ├── Agent 5: Criticality (LLM)   → agricultural scenario classification
    └── Agent 6: Decision (LLM)      → final action routing
                        ↓ Apache Kafka

CLOUD LAYER
├── Topics: sensor-data, fog-decisions, trust-events, policy-updates
├── Global orchestration and long-term storage
└── Federated learning aggregation
```

---

## Trust Levels

| Score     | Level  | Action                          |
|-----------|--------|---------------------------------|
| 0.8 - 1.0 | HIGH   | Act locally (open valve, etc.)  |
| 0.5 - 0.8 | MEDIUM | Consult validation agent        |
| 0.0 - 0.5 | LOW    | Reject + notify cloud           |

---

## Trust Score Composition (Agent 3)

| Factor       | Weight | Description                              |
|--------------|--------|------------------------------------------|
| Identity     | 35%    | Is sensor in the trusted registry?       |
| Freshness    | 25%    | How old is the reading? (replay defense) |
| Consistency  | 40%    | Does TinyML output match raw data?       |

---

## Agricultural Scenarios (Agent 5)

Agent 5 classifies each reading into one of these scenarios:

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
11. Normal

---

## Security Features

- **Zero Trust**: every reading verified before any processing begins
- **Replay attack detection**: timestamp freshness scoring with sharp penalty after 5 minutes
- **Prompt injection protection**: action whitelist prevents LLM from triggering unauthorized commands
- **Cryptographic identity attestation**: simulated sensor registry (maps to Trust Plane in Figure 1)
- **Audit logging**: every decision logged with full context to `logs/decisions.json`
- **Early exit**: pipeline stops at Agent 3 if trust score is too low, saving compute

---

## Project Structure

```
AgenticAiFog/
│
├── agents/
│   ├── __init__.py
│   ├── data_validation_agent.py   # Agent 1 - Rules based
│   ├── timestamp_agent.py         # Agent 2 - Rules based
│   ├── trust_score_agent.py       # Agent 3 - Rules based
│   ├── value_sanity_agent.py      # Agent 4 - Rules based
│   ├── criticality_agent.py       # Agent 5 - LLM powered (Groq)
│   └── decision_agent.py          # Agent 6 - LLM powered (Groq)
│
├── pipeline.py                    # Orchestrates all 6 agents
├── action_handler.py              # Whitelisted action execution
├── validation_agent.py            # Second opinion for MEDIUM trust
├── cloud_interface.py             # Kafka simulation + cloud escalation
├── logger.py                      # Audit trail (JSON)
├── main.py                        # Entry point
│
├── data/
│   └── archive/
│       └── Crop_recommendationV2.csv
│
└── logs/
    └── decisions.json             # Auto-generated audit log
```

---

## Dataset

Smart Farming Dataset 2024 (SF24) from Kaggle.
23 agricultural features per reading:

- Soil: NPK levels, pH, moisture, organic matter, soil type
- Environment: temperature, humidity, rainfall, wind speed, CO2
- Crop: growth stage, crop density, pest pressure, irrigation frequency
- Derived: THI, WAI, NBR, PP, SFI (used for consistency cross-checking)

---

## Tech Stack

| Component       | Technology                        |
|-----------------|-----------------------------------|
| Language        | Python 3.x                        |
| Agent Framework | LangChain + LangChain-Core        |
| LLM             | Groq API (Llama 3.1 8B Instant)   |
| Data Processing | Pandas                            |
| Messaging       | Apache Kafka (simulated)          |
| Configuration   | python-dotenv                     |

---

## How to Run

```bash
# 1. Clone and navigate to project
cd AgenticAiFog

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# 3. Install dependencies
pip install langchain langchain-groq langchain-core python-dotenv pandas

# 4. Add Groq API key
echo "GROQ_API_KEY=your_key_here" > .env

# 5. Run
python main.py
```

---

## Example Output

```
─── Reading 2 ───────────────────────────
Sensor: SENSOR_001 | Moisture: 12.9%
[Agent 1 - Validation] ✓ Data validation passed
[Agent 2 - Timestamp]  ✓ Timestamp valid
[Agent 3 - Trust]      ✓ Score: 1.0 | Level: HIGH
[Agent 4 - Sanity]     ✓ 8/8 fields passed sanity check
[Agent 5 - Criticality] ⚠ Scenario: Water Shortage | Severity: high
[Agent 6 - Decision]   → act_locally | Action: irrigate
[ACTION] Executing: irrigate
Result: irrigate_executed

─── Reading 5 ───────────────────────────
Sensor: SENSOR_001 | Moisture: 85.0%
[Agent 3 - Trust]      ✓ Score: 0.509 | Level: MEDIUM
[Agent 5 - Criticality] ✓ Scenario: Normal | Severity: low
[Agent 6 - Decision]   → validate | Action: validation
[VALIDATION] Verdict: escalate - requires cloud validation
Result: escalated_to_cloud
```

---

## Mapping to Architecture Figures

| Figure 1 Block                        | This Project                     |
|---------------------------------------|----------------------------------|
| Cryptographic Identity & Attestation  | SENSOR_REGISTRY in Agent 1       |
| Runtime Observability & Audit Logs    | logger.py                        |
| Agentic Decision Loop                 | pipeline.py                      |
| Policy Enforcement Point (PEP)        | action_handler.py whitelist      |
| Trust Scoring Engine                  | Agent 3 + trust_score_agent.py   |
| Local Anomaly Detection               | Agent 4 + 5 combined             |
| Multi-Agent Coordination              | pipeline.py orchestration        |
| Cloud Domain                          | cloud_interface.py               |

---

## Authors

Lion
