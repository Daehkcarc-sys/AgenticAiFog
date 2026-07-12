# Agentic AI Fog — Trust-Oriented Agricultural Digital Twin

> **Fog Node Implementation** · Python 3.14 · LangChain + Groq · Zero Trust

A production-quality research prototype implementing the Fog layer of a
**Trust-Oriented Cloud–Fog–Edge Agricultural Digital Twin Architecture**.
Combines deterministic rule engines with LLM-powered reasoning to validate
sensor telemetry, classify agricultural scenarios, and enforce trust-aware
actuation policies — all within the resource constraints of a Fog node.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [The Four-Layer Fog Architecture](#the-four-layer-fog-architecture)
3. [Execution Pipeline](#execution-pipeline)
4. [Decision Flow (LLM Avoidance Strategy)](#decision-flow-llm-avoidance-strategy)
5. [Trust Model](#trust-model)
6. [Agricultural Scenarios](#agricultural-scenarios)
7. [Security Features](#security-features)
8. [Benchmarking & Metrics](#benchmarking--metrics)
9. [Project Structure](#project-structure)
10. [Quick Start](#quick-start)
11. [Example Output](#example-output)
12. [Architecture Mapping](#architecture-mapping)
13. [Research & Publication](#research--publication)
14. [Authors](#authors)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLOUD LAYER                                   │
│  Long-term storage · Global orchestration · Digital Twins       │
│  Policy Administration Point (PAP) · Global analytics           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Kafka (simulated)
┌──────────────────────────┴──────────────────────────────────────┐
│                    FOG LAYER  ← this project                    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   TRUST LAYER                            │   │
│  │  Agent 1: Data Validation  ·  Agent 2: Timestamp        │   │
│  │  Agent 3: Trust Score      ·  Agent 4: Value Sanity     │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 CONTEXT LAYER  (external)                │   │
│  │  Historical trends · Rolling averages · Derived features │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │               INTELLIGENCE LAYER                         │   │
│  │  Agent 5: Criticality  ·  DecisionCache                 │   │
│  │  Agent 6: Decision     ·  (rules → cache → LLM → cloud) │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             ↓                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │               ENFORCEMENT LAYER                          │   │
│  │  ActionHandler (PEP)  ·  ValidationAgent                │   │
│  │  CloudInterface                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Cross-cutting: FogLogger · PipelineMetrics · DecisionCache    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ LoRa / LoRaWAN (simulated)
┌──────────────────────────┴──────────────────────────────────────┐
│                    EDGE LAYER                                    │
│  Soil sensors · Water actuators · Smart machinery              │
│  Field gateways · Lightweight Digital Twins · TinyML           │
└─────────────────────────────────────────────────────────────────┘
```

The Fog node is the system's **autonomous decision-making core**. It processes
sensor telemetry locally, applies Zero Trust validation, and only escalates to
the Cloud when trust is low or decisions are ambiguous. This minimizes latency,
reduces bandwidth, and keeps the farm operational during connectivity loss.

---

## The Four-Layer Fog Architecture

### 1. Trust Layer (Agents 1–4)

Deterministic, sub-millisecond rule engines that form the **first line of defense**.

| Agent | File | Responsibility | Rejects? |
|-------|------|---------------|----------|
| **DataValidationAgent** | `agents/data_validation_agent.py` | Sensor identity, schema, TinyML format | Yes |
| **TimestampAgent** | `agents/timestamp_agent.py` | Freshness scoring, replay attack detection | Yes (≥600s) |
| **TrustScoreAgent** | `agents/trust_score_agent.py` | Composite trust: identity 35% + freshness 25% + consistency 40% | Yes (<0.5) |
| **ValueSanityAgent** | `agents/value_sanity_agent.py` | Physical range + extreme outlier + semantic consistency | Yes (impossible values) |

**Early exit**: Any Trust Layer agent can short-circuit the pipeline, preventing
costly LLM calls for untrusted data. Unknown sensors, stale timestamps, and
physically impossible readings never reach the Intelligence Layer.

### 2. Context Layer (External Dependency)

*Implemented by another developer. Not part of this repository.*

Will provide: historical trends, rolling averages, derived agricultural features,
anomaly indicators, and semantic context. The Intelligence Layer is designed to
consume Context objects when available.

### 3. Intelligence Layer (Agents 5–6 + Cache)

LLM-powered reasoning components with deterministic pre-gates to minimize API usage.

| Component | File | Responsibility |
|-----------|------|---------------|
| **CriticalityAgent** | `agents/criticality_agent.py` | Classify agricultural scenario (8 classes), determine severity |
| **DecisionCache** | `decision_cache.py` | Bounded in-memory cache avoiding redundant LLM calls |
| **DecisionAgent** | `agents/decision_agent.py` | Hierarchical decision: rules → cache → LLM → cloud |

### 4. Enforcement Layer

| Component | File | Responsibility |
|-----------|------|---------------|
| **ActionHandler (PEP)** | `action_handler.py` | Policy Enforcement Point: whitelist-gated actuation, trust routing |
| **ValidationAgent** | `validation_agent.py` | Second-opinion LLM validator for MEDIUM trust decisions |
| **CloudInterface** | `cloud_interface.py` | Simulated Kafka + cloud escalation + rejection notification |

---

## Execution Pipeline

```
Sensor Telemetry (CSV / simulated)
│
▼
┌─ Trust Layer ──────────────────────────────────────────┐
│                                                        │
│  Agent 1: Data Validation                              │
│  ├─ Check sensor identity in SensorRegistry            │
│  ├─ Verify all REQUIRED_FIELDS present                 │
│  ├─ Validate TinyML output format                      │
│  ├─ Check recommended_action in ALLOWED_ACTIONS        │
│  └─ Verify confidence ∈ [0, 1]                         │
│  → FAIL: REJECT (unknown sensor / malformed data)      │
│                                                        │
│  Agent 2: Timestamp                                    │
│  ├─ Parse ISO 8601 timestamp                           │
│  ├─ age < 60s  → freshness 1.0                        │
│  ├─ age < 180s → freshness 0.8                        │
│  ├─ age < 300s → freshness 0.6                        │
│  ├─ age < 600s → freshness 0.3                        │
│  └─ age ≥ 600s → REJECT (possible replay attack)      │
│                                                        │
│  Agent 3: Trust Score                                  │
│  ├─ identity_score = 1.0 (verified by Agent 1)         │
│  ├─ consistency = cross-check TinyML vs soil moisture  │
│  └─ composite = 0.35·id + 0.25·fresh + 0.40·consist   │
│  → FAIL if < 0.5: REJECT                              │
│                                                        │
│  Agent 4: Value Sanity                                 │
│  ├─ Physical range check per field (VALID_RANGES)      │
│  ├─ Extreme outlier detection (2× range multiplier)    │
│  ├─ Semantic consistency with TinyML recommendation    │
│  └─ Hard-reject on physically impossible values        │
│  → FAIL if temp=999, humidity=999, etc.                │
└────────────────────────────────────────────────────────┘
│
▼  (Context Layer — external — not yet integrated)
│
┌─ Intelligence Layer ───────────────────────────────────┐
│                                                        │
│  Agent 5: Criticality                                  │
│  ├─ Deterministic pre-gate: skip LLM if clearly normal │
│  ├─ LLM classifies into 8 agricultural scenarios       │
│  └─ Falls back to "Normal" on API failure              │
│                                                        │
│  Agent 6: Decision (3-tier hierarchy)                  │
│  ├─ Tier 1: Deterministic rules (~0.01ms)              │
│  │   · HIGH + simple action → act_locally              │
│  │   · LOW → reject                                    │
│  ├─ Tier 2: DecisionCache lookup (~0.01ms)             │
│  │   · SHA-256 context hashing, 0.05 trust buckets     │
│  │   · FIFO eviction, TTL expiration                   │
│  ├─ Tier 3: LLM reasoning (~170ms)                     │
│  │   · Only invoked when rules + cache miss            │
│  └─ Falls back to "escalate → cloud" on API failure    │
└────────────────────────────────────────────────────────┘
│
▼
┌─ Enforcement Layer ────────────────────────────────────┐
│                                                        │
│  ActionHandler (PEP)                                   │
│  ├─ HIGH   → execute(action)  [whitelist-gated]        │
│  ├─ MEDIUM → ValidationAgent → confirm | escalate      │
│  └─ LOW    → reject_and_alert → CloudInterface         │
│                                                        │
│  Audit: FogLogger → logs/decisions.json                │
│  Metrics: PipelineMetrics → logs/metrics.json          │
└────────────────────────────────────────────────────────┘
```

---

## Decision Flow (LLM Avoidance Strategy)

The system is designed to **minimize LLM calls** — the most expensive operation
on resource-constrained Fog hardware. Each decision passes through increasingly
expensive resolution tiers:

```
Incoming Context
│
├─► Tier 1: Deterministic Rules  (~0.01ms, no I/O)
│   HIGH trust + simple action? → decide immediately
│   LOW trust?                  → reject immediately
│   MEDIUM or complex?          → fall through
│
├─► Tier 2: Decision Cache      (~0.01ms, in-memory)
│   Similar context seen recently? → reuse decision
│   Cache miss?                    → fall through
│
├─► Tier 3: LLM Reasoning       (~170ms, HTTPS → Groq)
│   Invoke Llama 3.1 8B with full pipeline context
│   Store result in cache for future reuse
│
└─► Tier 4: Cloud Escalation    (fallback only)
    LLM unavailable after retries? → escalate to cloud
```

**Expected LLM savings**: In a typical 50-reading run with mixed scenarios,
~85% of decisions resolve at Tier 1 (rules) or Tier 2 (cache), avoiding the
LLM entirely.

---

## Trust Model

### Trust Levels

| Score | Level | Action |
|-------|-------|--------|
| 0.8 – 1.0 | **HIGH** | Execute locally via whitelist |
| 0.5 – 0.8 | **MEDIUM** | Consult ValidationAgent → confirm or escalate |
| 0.0 – 0.5 | **LOW** | Reject + notify Cloud |

### Trust Score Composition

| Factor | Weight | Description |
|--------|--------|-------------|
| Identity | 35% | Sensor in trusted registry? (binary: 0.0 or 1.0) |
| Freshness | 25% | Reading age — decays from 1.0 (<60s) to 0.0 (≥600s) |
| Consistency | 40% | TinyML recommendation matches raw sensor data? |

**Early exit at 0.5** — readings below this threshold skip all downstream agents.

---

## Agricultural Scenarios

The CriticalityAgent classifies each reading into one of 8 canonical scenarios
defined in the `CriticalityScenario` enum (`models.py`):

| # | Scenario | Criteria |
|---|----------|----------|
| 1 | **Normal** | All readings within expected ranges |
| 2 | **Water deficit** | Low soil moisture, insufficient rainfall |
| 3 | **Flooding** | Very high soil moisture + significant rainfall |
| 4 | **Fire or heat stress** | Temperature exceeds crop-safe thresholds |
| 5 | **Crop disease risk** | High humidity + temperature → fungal conditions |
| 6 | **Pest infestation risk** | Warm + humid conditions persist |
| 7 | **Soil degradation** | pH or nutrients far from optimal |
| 8 | **Equipment failure** | Physically impossible sensor values |

The LLM prompt is **dynamically generated** from the enum, guaranteeing that
scenario labels can never drift from the data model.

---

## Security Features

| Feature | Implementation |
|---------|---------------|
| **Zero Trust** | Every reading fully verified before any processing |
| **Cryptographic identity** | `SensorRegistry` with case-insensitive lookup |
| **Replay attack detection** | Timestamp freshness with 300s hard limit, 600s absolute cutoff |
| **Continuous authorization** | Trust score recomputed on every reading |
| **Action whitelist (PEP)** | `ACTION_WHITELIST` blocks unauthorized LLM actions |
| **Prompt injection protection** | JSON-only response format, structured parsing with fallbacks |
| **Audit logging** | `FogLogger` — JSON audit trail with in-memory caching |
| **LLM resilience** | `safe_invoke` with 3 attempts, exponential backoff, graceful fallback |
| **Graceful degradation** | Every LLM agent has a safe fallback on persistent API failure |
| **Early exit** | 4 independent early-exit gates (Agents 1, 2, 3, 4) |

---

## Benchmarking & Metrics

`PipelineMetrics` (`metrics.py`) collects zero-overhead per-agent latency,
trust score distributions, scenario histograms, decision source breakdowns,
and result distributions.

```python
metrics = PipelineMetrics()
pipeline = FogPipeline(metrics=metrics, cache=DecisionCache(max_size=64))

# ... run pipeline ...

print(metrics.report())       # formatted console summary
metrics.to_dict()             # JSON-serializable for pandas/matplotlib
```

### Metrics Collected

| Category | Metrics |
|----------|---------|
| **Per-agent latency** | avg, median, p99, min, max (ms) |
| **Trust scores** | mean, median, stdev, min, max |
| **Scenarios** | count + percentage per scenario |
| **Decisions** | act_locally / validate / escalate counts |
| **Decision sources** | rule / cache / llm / cloud breakdown |
| **Actions** | irrigate / stop_irrigation / etc. distribution |
| **Results** | executed / rejected / cloud_decided distribution |

### Decision Cache Statistics

```python
cache_stats = pipeline.cache_stats
# {'size': 2, 'max_size': 64, 'hits': 6, 'misses': 2,
#  'evictions': 0, 'hit_rate': 0.75, 'ttl_seconds': 300}
```

---

## Project Structure

```
AgenticAiFog/
│
├── agents/                          # Fog agent implementations
│   ├── __init__.py                  # Package exports
│   ├── data_validation_agent.py     # Trust Layer — identity + schema validation
│   ├── timestamp_agent.py           # Trust Layer — freshness + replay detection
│   ├── trust_score_agent.py         # Trust Layer — composite trust scoring
│   ├── value_sanity_agent.py        # Trust Layer — physical + semantic sanity
│   ├── criticality_agent.py         # Intelligence Layer — LLM scenario classifier
│   └── decision_agent.py            # Intelligence Layer — hierarchical decision maker
│
├── pipeline.py                      # 4-layer orchestrator (FogPipeline)
├── action_handler.py                # Enforcement Layer — PEP with DI
├── validation_agent.py              # Enforcement Layer — second-opinion validator
├── cloud_interface.py               # Enforcement Layer — cloud escalation (Kafka sim)
│
├── models.py                        # Enums + FogAgentResult dataclasses
├── contracts.py                     # TypedDicts for dict-based interfaces
├── config.py                        # All constants, thresholds, registries
├── llm_factory.py                   # Centralized LLM config + safe_invoke helper
├── decision_cache.py                # Bounded in-memory decision cache
├── metrics.py                       # PipelineMetrics — benchmarking infrastructure
├── logger.py                        # FogLogger — cached JSON audit trail
├── sensor_registry.py               # Cryptographic identity validation
├── utils.py                         # JSON parsing utilities
├── main.py                          # Entry point — demo driver + metrics export
│
├── trust_scorer.py                  # [DEPRECATED] Legacy monolithic trust scorer
├── fog_agent.py                     # [DEPRECATED] Legacy monolithic agent
│
├── data/archive/                    # Dataset directory
│   └── Crop_recommendationV2.csv    # Smart Farming Dataset 2024 (Kaggle)
│
└── logs/                            # Runtime output (gitignored)
    ├── decisions.json               # Auto-generated audit trail
    └── metrics.json                 # Auto-generated benchmark data
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- [Groq API key](https://console.groq.com) (free tier works)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/Daehkcarc-sys/AgenticAiFog.git
cd AgenticAiFog

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install langchain langchain-groq langchain-core python-dotenv pandas

# 4. Configure your Groq API key
echo "GROQ_API_KEY=gsk_your_key_here" > .env

# 5. Run the demo (50 readings + full metrics report)
python main.py
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Yes | — | Groq API key for LLM inference |
| `GROQ_MODEL` | No | `llama-3.1-8b-instant` | Model name override for A/B testing |

---

## Example Output

```
[Agent 1 - Validation] PASS Data validation passed
[Agent 2 - Timestamp]  PASS Timestamp valid
[Agent 3 - Trust]      PASS Score: 1.0 | Level: TrustLevel.HIGH
[Agent 4 - Sanity]     PASS 8/8 fields passed sanity check
[Agent 5 - Criticality] OK Scenario: Normal | Severity: low
[Agent 6 - Decision]   -> act_locally | Action: irrigate | source: rule
[ACTION] Executing: irrigate

[Agent 1 - Validation] PASS Data validation passed
[Agent 2 - Timestamp]  PASS Timestamp valid
[Agent 3 - Trust]      PASS Score: 0.509 | Level: TrustLevel.MEDIUM
[Agent 4 - Sanity]     FAIL Physically impossible values in: ['temperature'].
                       Anomalies: temperature: EXTREME outlier (999, range [-20, 60])
[REJECT] Physically impossible values in: ['temperature']

==================================================
        FOG PIPELINE METRICS REPORT
==================================================
  Total readings      : 50
--------------------------------------------------
  Trust Score Distribution:
    Mean   : 0.9386    Median : 1.0000    Stdev  : 0.1736
--------------------------------------------------
  Agent Latencies (ms):
    criticality           avg=  284.27  median=  173.83  p99= 1056.24
    data_validation       avg=    0.01  median=    0.01  p99=    0.01
    decision              avg=   22.67  median=    0.01  p99=  181.30
    timestamp             avg=    0.01  median=    0.01  p99=    0.02
    trust_score           avg=    0.01  median=    0.01  p99=    0.01
    value_sanity          avg=    0.01  median=    0.01  p99=    0.02
--------------------------------------------------
  Scenario Distribution:
    Normal                        35  ( 70.0%)
    Water deficit                 15  ( 30.0%)
--------------------------------------------------
  Decision Distribution:
    act_locally                   42  ( 84.0%)
    validate                       8  ( 16.0%)
--------------------------------------------------
  Decision Source:
    rule                          34  ( 68.0%)
    cache                          8  ( 16.0%)
    llm                            8  ( 16.0%)
==================================================

Decision Cache: 8 hits / 2 misses (80.0% hit rate, 2/64 entries)
```

---

## Architecture Mapping

How each Fog component maps to the Trust-Oriented Cloud–Fog–Edge reference
architecture (Figure 1):

| Architecture Block | Implementation |
|--------------------|---------------|
| Cryptographic Identity & Attestation | `sensor_registry.py` + Agent 1 |
| Score-Based Continuous Authorization | Agent 3 + `TrustLevel` enum routing |
| Runtime Observability & Audit Logs | `logger.py` + `metrics.py` |
| Autonomous Recovery Manager | `safe_invoke` retry + fallback system |
| Multi-Agent Coordination | `pipeline.py` 4-layer orchestration |
| Policy Enforcement Point (PEP) | `action_handler.py` + `ACTION_WHITELIST` |
| Agentic Decision Loop | `DecisionAgent` 3-tier hierarchy |
| Local Anomaly Detection | Agents 4 + 5 combined |
| Local Fusion & Feature Extraction | `ValueSanityAgent` + trust composition |
| Fog Microservices | Each agent is an independent service |
| Cloud Domain (PAP) | `cloud_interface.py` |
| Digital Twins | *(Context Layer — external dependency)* |

---

## Research & Publication

### Current Readiness

The implementation is suitable for an **internship report, workshop paper, or
conference demo track**.  It provides:

- Reproducible benchmarking infrastructure
- Per-agent latency measurements (avg, median, p99)
- Trust score distributions with statistical summaries
- Decision source tracking (rule vs cache vs LLM vs cloud)
- Scenario classification histograms
- JSON-exportable metrics for pandas/matplotlib analysis

### Suggested Extensions for Stronger Publication

- Baseline comparisons (rule-only pipeline, different LLM models)
- Ablation study (remove Agent 3, Agent 5, or cache)
- Statistical significance with larger datasets
- False positive / false negative analysis
- Integration with real sensor hardware
- Context Layer integration for temporal reasoning

---

## Authors

Lion


