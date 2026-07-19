# Agentic AI Fog - Trust-Oriented Agricultural Digital Twin

Fog-node implementation for a Trust-Oriented Cloud-Fog-Edge Agricultural Digital
Twin architecture. The project focuses on local, context-aware, trust-aware
decision-making in the fog domain, with optional cloud, Kafka, actuator, ML, and
edge integrations.

Current code owners:

- Zaaa / Aziza and Lion: agentic fog pipeline, trust, context, decisions, enforcement.
- Sonic and Sarra: ML scenario modeling and dataset/model evaluation.
- Limon: Kafka/cloud synchronization.
- 3otri: edge layer, TinyML, hardware telemetry, and actuator integration.
- Digital twin owner: TBD.

---

## Table of Contents

1. [Current Status](#current-status)
2. [Architecture Overview](#architecture-overview)
3. [Pipeline Layers](#pipeline-layers)
4. [Team Handover](#team-handover)
5. [Project Structure](#project-structure)
6. [Quick Start](#quick-start)
7. [Configuration](#configuration)
8. [Tests](#tests)
9. [Architecture Mapping](#architecture-mapping)
10. [Authors](#authors)

---

## Current Status

This repository implements the fog-domain agentic pipeline. It is not just the
old diagram anymore; several pieces that were previously simulated now have
configurable adapters or local persistent stores.

Implemented:

- Trust layer: schema validation, timestamp freshness, trust scoring, value sanity.
- Context layer: rolling history, averages, slopes, variance, feature extraction,
  semantic context, and multi-level anomaly detection.
- Decision layer: local-first criticality classifier, decision cache, and final
  decision agent with rule/cache/LLM/cloud hierarchy.
- Enforcement layer: policy enforcement point, validation agent, actuator adapters,
  and cloud escalation.
- Support services: resource monitor, connectivity probe, persistent rule store,
  HMAC authorization, tamper-evident audit chain, persistent decision cache,
  model update metadata store, cloud sync queue/publisher.
- Tests: unit and smoke tests under `tests/`.

Still external/team-owned:

- Real ML scenario model training and evaluation: Sonic and Sarra.
- Real Kafka deployment and topics: Limon.
- Real hardware telemetry, TinyML firmware, and actuator wiring: 3otri.
- Digital twin service/API/schema: TBD owner.

---

## Architecture Overview

The repo implements the fog node in this flow:

```text
Edge / Field Devices
  soil sensors, water actuators, smart machinery, field gateways, TinyML
        |
        v
Fog Node - this repository
  Trust Layer
    data validation -> timestamp alignment -> trust score -> value sanity
  Context Layer
    rolling history -> feature extraction -> anomaly detection -> semantic context
  Decision Layer
    local criticality -> rule decision -> cache -> optional LLM -> optional cloud
  Enforcement Layer
    PEP -> actuator adapter -> logging/audit -> cloud sync
        |
        v
Cloud / Governance
  Kafka/cloud ingestion, long-term storage, policies, global analytics,
  digital twins, model updates
```

Default behavior is safe for local development:

- Actuator commands are written to `logs/queues/actuator_commands.jsonl`.
- Cloud events are written to `logs/queues/cloud_events.jsonl`.
- Decision cache and local rules are persisted under `state/`.
- Real MQTT, HTTP, Kafka, and command integrations are enabled through environment
  variables.

---

## Pipeline Layers

### 1. Trust Layer

| Component | File | Responsibility |
|---|---|---|
| Data validation | `agents/data_validation_agent.py` | Sensor identity, required fields, optional IoT fields, TinyML output format |
| Timestamp alignment | `agents/timestamp_agent.py` | Freshness scoring and replay/stale reading rejection |
| Trust scoring | `agents/trust_score_agent.py` | Composite trust from identity, freshness, and TinyML consistency |
| Value sanity | `agents/value_sanity_agent.py` | Physical ranges, extreme outliers, semantic consistency |

Required sensor fields are in `REQUIRED_FIELDS`. Optional IoT fields such as
`pressure`, `wind`, `salinity`, `tank_level`, `irrigation_flow`, `valve_state`,
`leaf_wetness`, `packet_loss`, and `sensor_trust_score` are in `OPTIONAL_FIELDS`.

### 2. Context Layer

Implemented mainly in:

- `agents/context_manager_agent.py`
- `anomaly_detector.py`

Responsibilities:

- Maintain bounded per-sensor sliding history.
- Compute rolling averages, trends/slopes, and variance.
- Extract derived agricultural features such as VPD, heat-humidity index, soil
  moisture band, and nutrient balance.
- Detect physical, statistical, and domain anomalies.
- Build a compact semantic summary for downstream decision-making.

### 3. Decision Layer

| Component | File | Responsibility |
|---|---|---|
| Criticality | `agents/criticality_agent.py` | Local-first classifier for 8 scenarios, optional remote fallback only on ambiguity |
| Decision cache | `decision_cache.py` | Persistent cache for repeated decision contexts |
| Decision agent | `agents/decision_agent.py` | Final decision via deterministic rules, cache, LLM, or cloud escalation |

`CriticalityAgent` is no longer always remote. It uses local deterministic
scenario scoring by default. Groq fallback is optional and controlled by:

- `CRITICALITY_MODE`
- `CRITICALITY_ENABLE_REMOTE_FALLBACK`
- `CRITICALITY_AMBIGUITY_MARGIN`

The ML team can later replace or augment this local classifier with a trained
model, but the current interface should remain:

```python
run(raw_readings: dict, tinyml_output: dict, context: dict | None = None) -> CriticalityResult
```

### 4. Enforcement Layer

| Component | File | Responsibility |
|---|---|---|
| PEP/action routing | `action_handler.py` | Trust-based action routing and whitelist enforcement |
| Actuator adapters | `actuator_adapters.py` | Local queue, HTTP, MQTT, or shell-command actuator dispatch |
| Validation agent | `validation_agent.py` | Second-opinion LLM validator for medium-trust decisions |
| Cloud interface | `cloud_interface.py` | Cloud escalation, rejection events, summary publishing, model update hooks |
| Cloud sync adapters | `cloud_sync.py` | Local queue, HTTP, Kafka publishers, model update install/rollback metadata |

### 5. Cross-Cutting Support Services

Implemented in `support_services.py`:

- `ResourceMonitor`: CPU/disk plus optional memory/battery through `psutil`.
- `ConnectivityManager`: probes `CLOUD_HEALTH_URL` or Kafka bootstrap if configured.
- `LocalRuleStore`: persistent local rule/policy JSON with versioning.
- `SecurityAccessControl`: HMAC signatures, key rotation, authorization checks,
  tamper-evident audit chain.
- `CloudSyncStore`: durable queue for fog summaries.

---

## Team Handover

Use this section first if you are joining the project and do not want to read
the whole repo.

### Zaaa / Aziza and Lion - Agentic Fog Pipeline

Start here:

- `pipeline.py`: full orchestration order.
- `agents/context_manager_agent.py`: context layer.
- `anomaly_detector.py`: multi-level anomaly detection.
- `agents/criticality_agent.py`: local-first scenario classifier.
- `agents/decision_agent.py`: final action decision.
- `action_handler.py`: PEP and trust-based routing.
- `tests/test_fog_components.py`: current regression tests.

Main integration contract:

- Pipeline input is a sensor message dict with `sensor_id`, `timestamp`,
  `raw_readings`, and `tinyml_output`.
- Pipeline output is a result string such as `irrigate_queued`, `rejected: ...`,
  or `cloud_decided: ...`.
- Do not change `CriticalityAgent.run(...)` or `DecisionAgent.run(...)` signatures
  unless all downstream callers and tests are updated.

### Sonic and Sarra - ML Scenarios

Start here:

- `models.py`: `CriticalityScenario` enum. These are the 8 canonical labels.
- `agents/criticality_agent.py`: current local classifier and scoring rules.
- `anomaly_detector.py`: anomaly/domain findings available before classification.
- `data/` or `data/archive.zip`: dataset area.
- `tests/test_fog_components.py`: expected behavior for scenarios.

What you likely need to deliver:

- A labeled scenario dataset for the 8 `CriticalityScenario` classes.
- Evaluation metrics: accuracy, precision/recall, confusion matrix, false
  positives/false negatives.
- Optional embedded model artifact, for example `.tflite`, `.onnx`, or similar.
- A wrapper that preserves the existing return shape: `CriticalityResult`.

Recommended integration path:

- Keep the deterministic classifier as fallback.
- Add model inference behind the same `CriticalityAgent.run(...)` interface.
- Compare rule-only vs ML vs hybrid in tests/metrics.

### Limon - Kafka / Cloud Synchronization

Start here:

- `cloud_sync.py`: publisher adapters.
- `cloud_interface.py`: escalation, rejection, summary upload, model update hooks.
- `support_services.py`: `ConnectivityManager` and `CloudSyncStore`.
- `config.py`: `CLOUD_*` environment variables.

What you likely need to deliver:

- Real Kafka topic names and schemas for:
  - `sensor-data`
  - `trust-events`
  - `fog-decisions`
  - `critical-events` if needed
- Kafka producer/consumer deployment config.
- Retry/backoff and dead-letter strategy.
- Mapping between local queue events and Kafka messages.

Current default:

- If Kafka is not configured, cloud events are persisted locally in
  `logs/queues/cloud_events.jsonl`.

### 3otri - Edge, TinyML, Hardware

Start here:

- `agents/data_validation_agent.py`: accepted raw telemetry fields.
- `config.py`: `REQUIRED_FIELDS`, `OPTIONAL_FIELDS`, `VALID_RANGES`,
  `ALLOWED_ACTIONS`, `ACTION_WHITELIST`.
- `actuator_adapters.py`: actuator dispatch options.
- `action_handler.py`: how final decisions become actuator commands.

What you likely need to deliver:

- Real sensor message format from field gateways.
- TinyML output format:

```json
{
  "recommended_action": "irrigate",
  "confidence": 0.9,
  "anomaly_detected": false
}
```

- Optional HMAC signature generation for sensor messages.
- Real actuator backend using MQTT, HTTP, or local command mode.

Current default:

- Actuator commands are queued to `logs/queues/actuator_commands.jsonl`.

### Digital Twin Owner - TBD

Start here:

- `agents/context_manager_agent.py`: local state and aggregated context.
- `cloud_interface.py`: summary upload and model update hooks.
- `cloud_sync.py`: cloud publisher.
- `logger.py`: decision audit trail.

What you likely need to define:

- Digital twin entity schema: field, sensor, crop, actuator, scenario, decision.
- API or Kafka contract for local state/aggregated data.
- How cloud twin state pushes policies/model updates back to fog.
- Which data is long-term storage vs short-term fog context.

Recommended first contract:

- Consume compact fog summaries from cloud sync.
- Return policy/model update metadata that can be passed to
  `CloudInterface.receive_model_update(...)` or `LocalRuleStore.update(...)`.

---

## Project Structure

```text
AgenticAiFog/
  agents/
    data_validation_agent.py      Trust Layer - identity/schema/TinyML validation
    timestamp_agent.py            Trust Layer - freshness/replay checks
    trust_score_agent.py          Trust Layer - composite trust scoring
    value_sanity_agent.py         Trust Layer - physical/semantic sanity
    context_manager_agent.py      Context Layer - history/features/semantic context
    criticality_agent.py          Decision Layer - local-first scenario classifier
    decision_agent.py             Decision Layer - rule/cache/LLM/cloud decision

  pipeline.py                     Main FogPipeline orchestration
  anomaly_detector.py             Multi-level anomaly detection
  action_handler.py               Policy Enforcement Point
  actuator_adapters.py            Local queue/HTTP/MQTT/command actuator adapters
  cloud_interface.py              Cloud escalation and update interface
  cloud_sync.py                   Local queue/HTTP/Kafka publishers + model store
  support_services.py             Resource/connectivity/rules/security/cloud queue
  decision_cache.py               Persistent decision cache
  models.py                       Enums and dataclass result models
  contracts.py                    TypedDict contracts for context/cloud/validation
  config.py                       Constants and environment-backed configuration
  metrics.py                      Pipeline metrics
  logger.py                       JSON decision logs
  llm_factory.py                  Optional Groq/LangChain helper
  main.py                         Demo driver

  tests/test_fog_components.py    Regression tests

  logs/                           Runtime logs and local queues
  state/                          Persistent cache, rules, model metadata
  data/                           Dataset area

  fog_agent.py                    Deprecated legacy monolithic agent
  trust_scorer.py                 Deprecated legacy trust scorer
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- `pandas` for the demo dataset loader.
- Optional: Groq/LangChain only if you enable LLM paths.
- Optional: `paho-mqtt` for MQTT actuator mode.
- Optional: `kafka-python` for Kafka cloud sync mode.
- Optional: `psutil` for richer resource monitoring.

### Setup

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install pandas python-dotenv langchain langchain-groq langchain-core

# Optional integrations
pip install paho-mqtt kafka-python psutil

python -m unittest discover -s tests
python main.py
```

Groq is optional for the local-first criticality path, but still used by
`DecisionAgent` and `ValidationAgent` if execution reaches their LLM branches.

---

## Configuration

### Core LLM

| Variable | Default | Description |
|---|---:|---|
| `GROQ_API_KEY` | unset | Required only for Groq-backed LLM branches |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model name |

### Criticality

| Variable | Default | Description |
|---|---:|---|
| `CRITICALITY_MODE` | `local_first` | `local_first` or `local_only` |
| `CRITICALITY_ENABLE_REMOTE_FALLBACK` | `false` | Enables Groq fallback for ambiguous criticality only |
| `CRITICALITY_AMBIGUITY_MARGIN` | `1` | Score margin used to define ambiguity |

### Actuation

| Variable | Default | Description |
|---|---:|---|
| `ACTUATOR_MODE` | `local_queue` | `local_queue`, `http`, `mqtt`, or `command` |
| `ACTUATOR_HTTP_ENDPOINT` | unset | HTTP actuator endpoint |
| `ACTUATOR_MQTT_HOST` | unset | MQTT broker host |
| `ACTUATOR_MQTT_PORT` | `1883` | MQTT broker port |
| `ACTUATOR_MQTT_TOPIC` | `fog/actuators` | MQTT topic |
| `ACTUATOR_COMMAND_TEMPLATE` | unset | Command template, e.g. `irrigatectl {action}` |

### Cloud / Kafka

| Variable | Default | Description |
|---|---:|---|
| `CLOUD_SYNC_MODE` | `local_queue` | `local_queue`, `http`, or `kafka` |
| `CLOUD_HTTP_ENDPOINT` | unset | HTTP cloud ingestion endpoint |
| `CLOUD_KAFKA_BOOTSTRAP` | unset | Kafka bootstrap server list |
| `CLOUD_KAFKA_TOPIC` | `sensor-data` | Default summary topic |
| `CLOUD_HEALTH_URL` | unset | Connectivity probe URL |

### Security

| Variable | Default | Description |
|---|---:|---|
| `SECURITY_HMAC_SECRET` | `dev-fog-secret` | Shared secret for optional signed sensor messages |

---

## Tests

Run:

```bash
python -m unittest discover -s tests
python -m compileall .
```

Current tests cover:

- Optional IoT field validation.
- Context history and optional field tracking.
- Multi-level anomaly detection.
- Criticality scenarios: Normal, Water deficit, Flooding, Heat stress, Disease
  risk, Soil degradation, Equipment failure, and ambiguous local result.
- Pipeline smoke test with local-first criticality.
- HMAC signature and tamper-evident audit chain.
- Persistent local rule store.
- Cloud sync queue drain.
- Persistent decision cache.
- Actuator queue dispatch.
- Cloud publisher and model update store.

---

## Architecture Mapping

| Architecture Block | Current Implementation |
|---|---|
| Cryptographic identity and attestation | `sensor_registry.py`, `SecurityAccessControl`, optional HMAC signatures |
| Score-based continuous authorization | `TrustScoreAgent`, `TrustLevel`, PEP routing |
| Runtime observability and audit logs | `logger.py`, `metrics.py`, audit chain in `support_services.py` |
| Autonomous recovery manager | `safe_invoke` fallbacks, connectivity probing, local queues |
| Multi-agent coordination | `pipeline.py` |
| Fog microservices | Each agent/service is isolated by file/class |
| Policy Enforcement Point | `ActionHandler` + `ACTION_WHITELIST` |
| Local anomaly detection | `ValueSanityAgent` + `MultiLevelAnomalyDetector` |
| Local fusion and feature extraction | `ContextManagerAgent` |
| Agentic decision loop | `DecisionAgent` |
| Local state / aggregated data | context history, `DecisionCache`, local queues, `state/` stores |
| Cloud synchronization | `cloud_interface.py` + `cloud_sync.py` |
| Updated models | `ModelUpdateStore` metadata install/rollback |
| Digital twins | Interface pending; use context summaries and cloud sync outputs |

---

## Authors

- Lion
- Zaaa / Aziza

