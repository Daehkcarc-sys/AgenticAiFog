# Fog Layer Agentic AI — Smart Farm Digital Twin

## Overview

A trust-oriented multi-agent pipeline running on the fog layer of an agricultural IoT system.
Implements Zero Trust security principles with continuous sensor data validation and
LLM-powered decision making, aligned with the **Trust-Oriented Cloud–Fog–Edge Agricultural
Digital Twin Architecture**.

The pipeline processes 50 sensor readings in ~60 seconds (LLM-dependent), producing
publication-ready metrics including per-agent latency histograms, trust score distributions,
and scenario classification reports.

---

## System Architecture

```
EDGE LAYER
├── Soil sensors, water actuators, smart machinery
└── TinyML model → recommended action + confidence score
                        ↓ LoRa / LoRaWAN

FOG LAYER  (this project)
└── 6-Agent Pipeline
    │
    ├── Agent 1: Data Validation     → identity, required fields, TinyML format
    ├── Agent 2: Timestamp           → freshness scoring, replay attack detection
    ├── Agent 3: Trust Score         → composite score (identity + freshness + consistency)
    ├── Agent 4: Value Sanity        → physical range validation per feature
    ├── Agent 5: Criticality (LLM)   → agricultural scenario classification
    └── Agent 6: Decision (LLM)      → trust-based action routing
                        ↓ Apache Kafka (simulated)

CLOUD LAYER
├── Topics: sensor-data, fog-decisions, trust-events, policy-updates
├── Global orchestration and long-term storage
└── LLM-powered global decision making (CloudInterface)
```

---

## Trust Levels & Routing

| Score       | Level  | Action                                                |
|-------------|--------|-------------------------------------------------------|
| 0.8 – 1.0   | HIGH   | Execute locally via whitelist (irrigate, etc.)        |
| 0.5 – 0.8   | MEDIUM | Consult Validation Agent → confirm or escalate        |
| 0.0 – 0.5   | LOW    | Reject + notify cloud via rejection topic             |

Trust levels are enforced via the `TrustLevel` enum (`models.py`) throughout the pipeline —
no magic strings.

---

## Trust Score Composition (Agent 3)

| Factor       | Weight | Description                                     |
|--------------|--------|-------------------------------------------------|
| Identity     | 35%    | Sensor found in trusted registry?               |
| Freshness    | 25%    | Reading age (replay attack defense)             |
| Consistency  | 40%    | TinyML recommendation matches raw sensor data?  |

Early exit at 0.5 threshold — readings below this score skip LLM agents entirely.

---

## Agricultural Scenarios (Agent 5)

Agent 5 classifies each reading into one of 8 canonical scenarios, defined in
`CriticalityScenario` enum (`models.py`) and kept consistent across the entire codebase:

1. Normal
2. Water deficit
3. Flooding
4. Fire or heat stress
5. Crop disease risk
6. Pest infestation risk
7. Soil degradation
8. Equipment failure

---

## Security & Robustness

| Feature                         | Implementation                                       |
|---------------------------------|------------------------------------------------------|
| Zero Trust                      | Every reading verified at Agent 1 before processing  |
| Replay attack detection         | Timestamp freshness with 300s hard limit             |
| Action whitelist (PEP)          | `ACTION_WHITELIST` blocks unauthorized LLM commands  |
| Cryptographic identity          | `SensorRegistry` — maps to Trust Plane attestation   |
| Continuous authorization        | Trust score recomputed on every reading              |
| Audit logging                   | `FogLogger` — JSON audit trail with cached writes    |
| Early exit                      | Agent 3 gate stops pipeline if trust < 0.5           |
| LLM resilience                  | `safe_invoke` with retry + exponential backoff       |
| Graceful degradation            | Every LLM agent has a safe fallback on API failure   |

---

## Research & Benchmarking

The `PipelineMetrics` class (`metrics.py`) collects zero-overhead per-agent latencies,
trust score distributions, scenario histograms, and decision counts. After a run:

```python
print(metrics.report())          # formatted console summary
metrics.to_dict()                # JSON-serializable for pandas/matplotlib
```

Metrics are automatically persisted to `logs/metrics.json` after every `main.py` run.

Inter-agent contracts are documented via TypedDicts in `contracts.py` for IDE
autocompletion and static analysis.

---

## Project Structure

```
AgenticAiFog/
│
├── agents/
│   ├── __init__.py                  # Package exports
│   ├── data_validation_agent.py     # Agent 1 — Rules-based
│   ├── timestamp_agent.py           # Agent 2 — Rules-based
│   ├── trust_score_agent.py         # Agent 3 — Rules-based
│   ├── value_sanity_agent.py        # Agent 4 — Rules-based
│   ├── criticality_agent.py         # Agent 5 — LLM-powered (Groq)
│   └── decision_agent.py            # Agent 6 — LLM-powered (Groq)
│
├── pipeline.py                      # 6-agent orchestrator
├── action_handler.py                # Policy Enforcement Point (PEP)
├── validation_agent.py              # Second opinion for MEDIUM trust
├── cloud_interface.py               # Kafka simulation + cloud escalation
│
├── config.py                        # Constants, thresholds, registries
├── models.py                        # Enums & dataclasses (TrustLevel, CriticalityScenario…)
├── contracts.py                     # TypedDicts for inter-agent communication
├── metrics.py                       # PipelineMetrics — benchmarking & profiling
├── llm_factory.py                   # Centralized LLM config + safe_invoke helper
├── logger.py                        # FogLogger — cached JSON audit trail
├── sensor_registry.py               # Sensor identity validation
├── trust_scorer.py                  # [DEPRECATED] Legacy trust scorer
├── fog_agent.py                     # [DEPRECATED] Legacy monolithic agent
├── utils.py                         # JSON parsing utilities
├── main.py                          # Entry point (demo + metrics export)
│
├── data/
│   └── archive/
│       └── Crop_recommendationV2.csv
│
└── logs/
    ├── decisions.json               # Auto-generated audit log
    └── metrics.json                 # Auto-generated benchmark data
```

---

## Dataset

Smart Farming Dataset 2024 (SF24) from Kaggle.
23 agricultural features per reading:

- **Soil**: NPK levels, pH, moisture, organic matter, soil type
- **Environment**: temperature, humidity, rainfall, wind speed, CO₂
- **Crop**: growth stage, crop density, pest pressure, irrigation frequency
- **Derived**: THI, WAI, NBR, PP, SFI (cross-checking)

Required fields for the fog pipeline: `soil_moisture`, `temperature`, `humidity`,
`rainfall`, `ph`, `nitrogen`, `phosphorus`, `potassium`.

---

## Tech Stack

| Component         | Technology                                  |
|-------------------|---------------------------------------------|
| Language          | Python 3.14                                 |
| Agent Framework   | LangChain + LangChain-Core + LangChain-Groq |
| LLM               | Groq API (Llama 3.1 8B Instant)            |
| Data Processing   | Pandas                                      |
| Messaging         | Apache Kafka (simulated)                    |
| Benchmarking      | `time.perf_counter` + custom PipelineMetrics|
| Type Safety       | TypedDicts, Enums, dataclasses              |
| Configuration     | python-dotenv                               |

---

## Quick Start

```bash
# 1. Clone and navigate
cd AgenticAiFog

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# 3. Install dependencies
pip install langchain langchain-groq langchain-core python-dotenv pandas

# 4. Add your Groq API key
echo "GROQ_API_KEY=your_key_here" > .env

# 5. Run the demo (50 readings + metrics report)
python main.py
```

---

## Example Output

```
─── Reading 2 ───────────────────────────
Sensor: SENSOR_001 | Moisture: 12.9%
[Agent 1 - Validation] ✓ Data validation passed
[Agent 2 - Timestamp]  ✓ Timestamp valid
[Agent 3 - Trust]      ✓ Score: 1.0 | Level: TrustLevel.HIGH
[Agent 4 - Sanity]     ✓ 8/8 fields passed sanity check
[Agent 5 - Criticality] ⚠ Scenario: Water deficit | Severity: high
[Agent 6 - Decision]   → act_locally | Action: irrigate
[ACTION] Executing: irrigate
Result: irrigate_executed

─── Reading 6 ───────────────────────────
Sensor: SENSOR_001 | Moisture: 85.0%
[Agent 1 - Validation] ✓ Data validation passed
[Agent 2 - Timestamp]  ✓ Timestamp valid
[Agent 3 - Trust]      ✓ Score: 0.509 | Level: TrustLevel.MEDIUM
[Agent 4 - Sanity]     ✓ 6/8 fields passed sanity check
[Agent 5 - Criticality] ✓ Scenario: Normal | Severity: low
[Agent 6 - Decision]   → validate | Action: validation
[VALIDATION] Verdict: escalate — suspicious temp/humidity
[CLOUD] cloud_decided: validate and adjust parameters
Result: cloud_decided

==================================================
        FOG PIPELINE METRICS REPORT
==================================================
  Total readings      : 50
  Trust Score Distribution:
    Mean   : 0.9386    Median : 1.0000    Stdev  : 0.1736
  Agent Latencies (ms):
    criticality           avg=  284.27  median=  173.83
    data_validation       avg=    0.01  median=    0.01
    decision              avg=  172.05  median=  169.95
    timestamp             avg=    0.01  median=    0.01
    trust_score           avg=    0.01  median=    0.01
    value_sanity          avg=    0.01  median=    0.01
  Scenario Distribution:
    Normal                        35  ( 70.0%)
    Water deficit                 15  ( 30.0%)
  Decision Distribution:
    act_locally                   42  ( 84.0%)
    validate                       8  ( 16.0%)
==================================================
```

---

## Architecture Mapping

| Figure 1 Block                         | Implementation                          |
|----------------------------------------|-----------------------------------------|
| Cryptographic Identity & Attestation   | `sensor_registry.py` + Agent 1          |
| Score-Based Continuous Authorization   | Agent 3 + `TrustLevel` enum routing     |
| Runtime Observability & Audit Logs     | `logger.py` + `metrics.py`              |
| Autonomous Recovery Manager            | `safe_invoke` retry + fallback system   |
| Multi-Agent Coordination               | `pipeline.py` 6-agent orchestration     |
| Policy Enforcement Point (PEP)         | `action_handler.py` + `ACTION_WHITELIST`|
| Agentic Decision Loop                  | `pipeline.py` → `DecisionAgent` → PEP   |
| Local Anomaly Detection                | Agents 4 + 5 combined                   |
| Local Fusion & Feature Extraction      | `ValueSanityAgent` + trust composition  |
| Cloud Domain (PAP)                     | `cloud_interface.py`                    |
| Fog Microservices                      | Each agent is an independent service    |

---

## Authors

Lion

