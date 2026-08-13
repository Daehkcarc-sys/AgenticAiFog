# AgenticAiFog — Complete Project Overview

This document explains the entire AgenticAiFog project in depth: what problem it
solves, why the architecture is designed the way it is, how every component works,
how every tool is used, and how the code is structured. It is written so that
anyone can discuss the project fluently in an interview, a presentation, or a
paper defence.

---

## 1. What problem does this project solve?

Modern precision agriculture relies on dense networks of IoT sensors to monitor
soil moisture, temperature, humidity, pH, rainfall, and crop health. Farms in
remote or developing regions typically lack reliable internet connectivity. Sending
every raw sensor reading to a cloud server is:

- **Slow** — round-trip latency of 40–650 ms depending on terrestrial or satellite link.
- **Expensive** — satellite (NTN) data costs up to 150× more per megabyte than
  terrestrial 4G.
- **Unreliable** — the link may be offline entirely, leaving the farm with no
  decisions during outages.
- **Energy-intensive** — cloud round-trips dominate the energy budget of battery-
  powered edge nodes.

The traditional alternative — simple threshold rules at the edge — misses complex
multi-sensor patterns (e.g., heat stress combined with low moisture combined with
a drifting sensor) and cannot be updated without reprogramming every device.

**AgenticAiFog** proposes a three-tier agentic architecture:

```
[Edge device — Raspberry Pi / TinyML sensor node]
        ↓  (sensor_data topic, Kafka/Redpanda)
[Fog server — multi-agent pipeline on a local server or gateway]
        ↓  (fog_decisions, cloud_events topics)
[Cloud — storage, LLM escalation, digital twin, federated model updates]
```

At the fog tier, a pipeline of six specialised AI agents processes each reading
locally. Cloud is only contacted when the fog cannot reach a confident decision
and the link is available. This makes agricultural decision-making resilient,
fast, and cheap.

---

## 2. Research context and baselines

The project is structured around an academic evaluation comparing six system
configurations (B0 through B5) on the same synthetic workload:

| Baseline | Where decisions are made | Why it exists |
|---|---|---|
| B0 Cloud-only | Every reading goes to the cloud | Naive baseline; maximum bytes, maximum latency |
| B1 Edge-only | TinyML model on the sensor node | No fog, no cloud; lowest latency but no trust or context |
| B2 Static fog | Local rules on the fog server | Rules without trust, zone context, or LLM |
| B3 Direct LLM | Cloud LLM for every decision | Maximum intelligence but maximum cost and latency |
| B4 Trust fog | B2 plus trust-gated rejection | Low-trust readings are rejected locally before cloud upload |
| B5 Full system | Trust + zone context + NTN routing + digital twin | The proposed architecture |

The evaluation metric that distinguishes B5 from B0–B4 is the combination of:
- High decision coverage even when the link is offline (NTN-aware fallback).
- Low cloud bytes and communication cost (trust-gated local decisions).
- Competitive F1 on abnormal event detection (zone fusion improves classification).
- Full energy accounting (edge mJ + fog mJ + cloud mJ + NTN transmission).
- LLM cost tracking ($USD per B3 inference).

Statistical significance is verified by running each baseline over 30–50 seeds and
applying a paired Wilcoxon signed-rank test.

---

## 3. High-level architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Edge tier                                                  │
│  Raspberry Pi / microcontroller                             │
│  • TinyML model (TFLite / ONNX)                             │
│  • Canonical TelemetryRecord message                        │
│  • Kafka producer → sensor_data topic                       │
└────────────────────┬────────────────────────────────────────┘
                     │  Kafka / Redpanda
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Fog tier  (FogPipeline / ZoneFogPipeline)                  │
│                                                             │
│  Agent 1  DataValidationAgent    — schema + identity check  │
│  Agent 2  TimestampAgent         — freshness + UTC validity │
│  Agent 3  TrustScoreAgent        — composite trust [0,1]    │
│  Agent 4  ValueSanityAgent       — physical ranges + normals│
│  Context  ZoneContextManager     — rolling zone features    │
│  Anomaly  MultiLevelAnomalyDetector                         │
│  Fusion   MultimodalFusionAgent  — text/image/sensor fusion │
│  Agent 5  CriticalityAgent       — scenario classifier      │
│  Agent 6  DecisionAgent          — act / validate / escalate│
│  Enforce  ActionHandler          — actuator + cloud sync    │
└────────────────────┬────────────────────────────────────────┘
                     │  fog_decisions, cloud_events topics
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  Cloud tier                                                 │
│  • digital_twin_service  — DigitalTwinEngine                │
│  • cloud_storage_consumer — SQLite / PostgreSQL             │
│  • governance_consumer   — policy enforcement log           │
│  • dashboard             — HTTP dashboard (port 8050)       │
│  • FL model updates      — model_updates topic              │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. The fog pipeline — layer by layer

### Entry point

`main.py` reads a CSV or ZIP dataset (or receives live Kafka messages) and calls
`FogPipeline.run(sensor_data: dict)` for each reading. With `--kafka`, the
pipeline publishes results to the `fog_decisions` Kafka topic. With `--offline`,
no LLM API calls are made.

```bash
python main.py --kafka --kafka-bootstrap localhost:9092
python main.py --offline --limit 20
```

### FogPipeline (pipeline.py)

The pipeline is a sequential chain. Each step has a measured context window
(`PipelineMetrics`) and can short-circuit with a rejection if the check fails.

```
sensor_data (dict)
  │
  ├─ Agent 1: DataValidationAgent
  │   Checks: required fields present, sensor ID in trusted registry,
  │            all field types correct.
  │   Short-circuits on fail → reject_and_alert()
  │
  ├─ SecurityAccessControl.audit_context()
  │   Verifies HMAC signature if present. Appends to audit chain JSONL.
  │
  ├─ Agent 2: TimestampAgent
  │   Checks: ISO-8601 UTC timestamp, not stale (< 300 s), not future
  │            (> 5 s ahead), converts timezone-aware to UTC.
  │   Short-circuits on fail → reject
  │
  ├─ Agent 3: TrustScoreAgent
  │   Inputs: freshness_score, tinyml_output, raw_readings.
  │   Composite score = f(freshness, consistency, recommendation_match).
  │   Output: trust_score ∈ [0,1], trust_level ∈ {HIGH, MEDIUM, LOW}.
  │   LOW → reject.
  │
  ├─ Agent 4: ValueSanityAgent
  │   Checks VALID_RANGES (physical plausibility) and NORMAL_OPERATING_RANGES.
  │   Returns sanity_score and list of failed_fields.
  │
  ├─ ZoneContextManager (rolling context)
  │   Maintains a deque of recent readings per zone.
  │   Computes: mean, min, max, latest, linear slope per hour.
  │   Derives: soil-water deficit, vapour-pressure deficit (VPD).
  │   Detects: cross-sensor anomalies (spread between devices in the same zone).
  │
  ├─ MultiLevelAnomalyDetector
  │   Threshold + statistical anomaly detection at sensor, zone, farm levels.
  │
  ├─ MultimodalFusionAgent
  │   Accepts optional image, text, or spectral inputs alongside sensor data.
  │   Produces a semantic_summary string.
  │
  ├─ Agent 5: CriticalityAgent
  │   Local-first: deterministic rules for the 7 agricultural scenarios.
  │   If the local score is below a confidence margin and remote fallback is
  │   enabled, calls the LLM (Groq / OpenAI) with CRITICALITY_PROMPT.
  │   Returns: scenario, severity, critical flag, reasoning string.
  │
  ├─ Agent 6: DecisionAgent
  │   Routing: rule → cache → LLM.
  │   NTN/offline-aware: if link_state is "offline" or "ntn" and trust is
  │   MEDIUM, falls back to local validation instead of cloud escalation.
  │   Returns: decision (act_locally / validate / escalate / reject),
  │             action_required, confidence, source.
  │
  └─ ActionHandler
      HIGH trust + safe action + policy permission → act_locally (valve/pump).
      Other cases → queue_local, cloud_upload, or trigger_alert.
```

### Zone-aware variant: ZoneFogPipeline (simulation/zone_pipeline.py)

Wraps `FogPipeline` with `ZoneContextManager`. Accepts `TelemetryRecord` objects
directly (not raw dicts). For each record:
1. Updates the zone context window.
2. Attaches `zone_context` snapshot to the pipeline message.
3. Optionally advances the `DigitalTwinEngine` with the result.

```python
from simulation.zone_pipeline import ZoneFogPipeline
from digital_twin.simulator import DigitalTwinEngine

twin = DigitalTwinEngine()
zfp = ZoneFogPipeline(twin=twin)
result = zfp.run(record)          # TelemetryRecord
state = zfp.twin_dashboard()      # current twin dashboard dict
```

---

## 5. Telemetry schema (simulation/telemetry_schema.py)

Every message in the system — whether produced by the synthetic generator,
the Raspberry Pi firmware, or the Kafka consumer — must conform to
`TelemetryRecord`. This is the canonical contract shared by all tiers.

```python
@dataclass
class TelemetryRecord:
    event_id: str          # "evt-0012-1-1"
    device_id: str         # "zone-1-sensor-2"
    zone_id: str           # "zone-1"
    timestamp: datetime    # UTC-aware
    sequence_number: int   # monotone counter per device
    readings: dict         # {"temperature": 34.2, "soil_moisture": 18.0, ...}
    tinyml_class: str      # "Water deficit"
    tinyml_confidence: float  # 0.0–1.0
    tinyml_model_version: str
    actuator_state: dict   # {"valve_open": False, "pump_active": False}
    link_state: LinkState  # TERRESTRIAL | NTN | OFFLINE
    event_label: CriticalityScenario   # ground truth (simulation only)
    sensor_fault_label: SensorFault    # NONE | GRADUAL_DRIFT | RANDOM_DROPOUT | ...
    delivered: bool        # False if the packet was simulated as lost
    schema_version: str
```

`event_label` and `sensor_fault_label` are independent: a sensor can be drifting
while the zone is genuinely experiencing a water deficit.

---

## 6. Simulation system

### Synthetic generator (simulation/generator.py)

`SyntheticTelemetryGenerator(config, events, faults, connectivity).generate()`
produces a deterministic sequence of `TelemetryRecord` objects from a seed.

`SimulationConfig` controls:
- `zone_count`, `sensors_per_zone`, `seed`
- `duration_minutes`, `sample_interval_minutes` (default 10 min)

`EventInjection(zone_id, scenario, start_step, duration_steps)` injects an
agricultural event (water deficit, flooding, heat stress, etc.) into a specific
zone for a window of steps.

`FaultInjection(device_id, fault_type, start_step, duration_steps, field, magnitude)`
independently drifts, drops out, freezes, or loses packets for one sensor.

### Network model (simulation/network_model.py)

`MarkovConnectivityModel` is a seeded three-state Markov chain:

```
TERRESTRIAL ──(0.85)──▶ TERRESTRIAL
            ──(0.10)──▶ NTN
            ──(0.05)──▶ OFFLINE
```

Default parameters:

| State | Bandwidth | Base latency | Cost/MB |
|---|---:|---:|---:|
| Terrestrial | 10 MB/s | 40 ms | $0.01 |
| NTN (satellite) | 500 KB/s | 650 ms | $1.50 |
| Offline | 0 | — | $0 |

`model.next_state()` transitions the chain at each simulated step and assigns
`link_state` to each `TelemetryRecord`.

### BaselineSimulator (simulation/baselines.py)

`BaselineSimulator(baseline, twin=None, zone_fusion=True, high_freq_factor=1)`
runs a SimPy discrete-event simulation over a list of `TelemetryRecord` objects.

Each record is released into the SimPy environment at its real elapsed-time offset.
The baseline logic fires after simulated network and processing delays.

`run(records) → list[DecisionOutcome]`
`run_with_twin(records) → (list[DecisionOutcome], dict)`

`DecisionOutcome` fields:

| Field | Description |
|---|---|
| `baseline` | Which baseline produced this outcome |
| `event_id` | Record identifier |
| `true_event` | Ground-truth `CriticalityScenario` |
| `predicted_event` | Predicted scenario (None if rejected) |
| `decision_made` | Whether a real decision was reached |
| `latency_ms` | End-to-end simulated latency |
| `bytes_to_cloud` | Bytes transmitted to cloud |
| `communication_cost` | USD cost of transmission |
| `energy_units` | Legacy coarse energy proxy |
| `edge_energy_mj` | Millijoules at edge (TinyML inference) |
| `fog_energy_mj` | Millijoules at fog node |
| `cloud_energy_mj` | Millijoules at cloud + transmission |
| `llm_cost` | USD LLM API cost proxy (B3 only) |
| `twin_risk_index` | Digital twin zone risk after this decision (B5) |
| `trust_score` | Trust value used (B4/B5) |
| `decision_source` | `"rule"`, `"tinyml"`, `"llm"`, `"cloud"`, `"trust_reject"` |

### Experiment runner (simulation/experiment_runner.py)

```bash
# Single seed, all baselines
python -m simulation.experiment_runner --baseline all --seed 5

# Multiple seeds, specific baseline
python -m simulation.experiment_runner --baseline B5 --seeds 1 2 3 4 5

# Save to JSON
python -m simulation.experiment_runner --baseline all --seeds 1 2 3 \
    --output results.json
```

`run_experiment(baseline, seed)` returns a `dict` with all metrics from
`summarize_outcomes()`.

`run_multi_seed(baselines, seeds)` returns per-baseline mean and std.

---

## 7. The digital twin (digital_twin/)

The digital twin is an in-memory forward model of the farm. It runs in parallel
with the fog pipeline and tracks how the farm state evolves over time.

### Entities (digital_twin/entities.py)

- `FarmEntity` — top-level container; holds zones, policies, event log.
- `ZoneEntity` — one crop zone; has soil state, crop state, sensors, actuators,
  risk index, state history.
- `SoilState` — moisture, pH, nitrogen, phosphorus, potassium, salinity.
- `CropEntity` — crop type, growth stage, disease/heat/pest risk floats.
- `SensorEntity` — trust score, last seen, last readings.
- `DecisionEntity` — last fog decision applied to this zone.
- `DigitalTwinEvent` — immutable event record appended on every fog summary.

### Process models (digital_twin/process_models.py)

Each model implements `step(zone, context) → trace_dict` and mutates the zone in
place. Three built-in models:

1. **SoilWaterBalanceModel** — evapotranspiration, rainfall infiltration, irrigation
   gain, drainage loss. Computes new soil moisture from weather and interventions.
2. **CropRiskModel** — disease risk (leaf wetness + humidity), heat stress
   (temperature), pest risk (temperature × humidity). Uses exponential moving
   averages with configurable memory coefficients.
3. **EquipmentDegradationModel** — hourly degradation rate; resets on
   `dispatch_maintenance` intervention.

Models are pluggable: `twin.register_process_model(model)` adds a custom one.
`twin.replace_process_models([...])` swaps all defaults.

### DigitalTwinEngine (digital_twin/simulator.py)

Key methods:

```python
twin = DigitalTwinEngine(farm_id="demo-farm")

# Feed a fog decision summary
twin.apply_fog_summary(payload)   # updates zone state, appends DigitalTwinEvent

# Advance time by N minutes
result = twin.step(minutes=10, weather={"temperature": 33, "rainfall": 0})

# Run N steps
results = twin.simulate(steps=24, minutes_per_step=60, weather_series=[...])

# Forward projection without modifying state
what_if = twin.what_if(zone_id="zone-1", scenario="irrigation", horizon_steps=3)

# Dashboard snapshot
state = twin.dashboard_state()

# Calibration
twin.apply_calibration(profile)
```

`what_if()` deep-copies the engine, runs the scenario forward, and returns a
`WhatIfResult` with `baseline_risk`, `projected_risk`, `delta`, `recommendation`,
and a step-by-step `trace`.

### What-if CLI (tools/what_if.py)

```bash
python -m tools.what_if --zone zone-1 --scenario irrigation --horizon 3
python -m tools.what_if --zone zone-2 --scenario disease_risk \
    --state state/digital_twin.db --output what_if_result.json
python -m tools.what_if --list-scenarios
```

Loads the latest twin state from `state/digital_twin.db` if provided, then
runs the forward projection and prints the full JSON result.

### Digital twin service (services/digital_twin_service.py)

Kafka consumer that subscribes to `fog_decisions` and `twin_sync` topics.
For each message it calls `twin.apply_fog_summary()` and periodically calls
`twin.step()` to advance the simulation clock. State is persisted to SQLite.

---

## 8. Kafka / Redpanda streaming stack

### Topics

| Topic | Partitions | Produced by | Consumed by |
|---|---|---|---|
| `sensor_data` | 3 | Edge device | FogPipeline |
| `fog_decisions` | 2 | FogPipeline | DigitalTwinService, cloud storage |
| `trust_events` | 1 | TrustScoreAgent | Cloud storage |
| `critical_events` | 1 | CriticalityAgent | Cloud alerts |
| `model_updates` | 1 | Cloud trainer | Edge/fog devices |
| `policy_updates` | 1 | GovernanceConsumer | FogPipeline |
| `dead_letter` | 1 | Failed consumers | Manual review |
| `twin_state` | 1 | DigitalTwinService | Dashboard |
| `twin_sync` | 1 | Cloud | DigitalTwinService |
| `twin_command` | 1 | Dashboard / operator | DigitalTwinService |

### Setup

```bash
# Start broker + console (dev)
docker compose up -d

# Create all topics
python -m tools.setup_topics --bootstrap localhost:9092

# Run fog agent with Kafka publishing
python main.py --kafka --kafka-bootstrap localhost:9092
```

### cloud_sync.py

`KafkaPublisher` uses a lazy-init singleton `KafkaProducer` (created on first
call to avoid holding a connection when the broker is not yet ready). The
producer uses `acks="all"` and `retries=3`.

`ReliableCloudPublisher` wraps any `CloudPublisher` with a local JSONL queue;
if the primary publish fails the message is durable and retried on the next run.

`build_cloud_publisher()` reads `CLOUD_SYNC_MODE`, `CLOUD_KAFKA_BOOTSTRAP`, and
`CLOUD_HTTP_ENDPOINT` from env vars **at call time** (not import time), so
`os.environ` overrides set by `main.py` before pipeline construction are visible.

---

## 9. Trust scoring

### TrustScoreAgent (agents/trust_score_agent.py)

Computes a composite trust score from three components:
1. **Freshness** — provided by TimestampAgent as a float ∈ [0,1].
2. **Consistency** — how well raw readings agree with each other (no single
   field wildly out of range while others are normal).
3. **Recommendation match** — whether the TinyML `recommended_action` is
   consistent with the raw readings (e.g., TinyML says `irrigate` but soil
   moisture is 90 % is suspicious).

Thresholds (from `config.py`):
- `HIGH` ≥ 0.80 — act locally allowed
- `MEDIUM` ≥ 0.50 — validate or escalate
- `LOW` < 0.50 — reject reading

### Trust ROC-AUC (evaluation/trust_roc.py)

Evaluates whether trust scores separate faulty sensors from healthy ones without
access to the true fault label at inference time (the label is used only during
evaluation).

```python
from evaluation.trust_roc import compute_roc_auc, samples_from_records
samples = samples_from_records(records)   # uses _simulated_trust as proxy
auc = compute_roc_auc(samples)            # 1.0 = perfect; 0.5 = random
```

### SensorTrustHistory (evaluation/trust_history.py)

Detects four fault patterns from the trust trajectory alone (no ground truth):

| Pattern | Detection criterion |
|---|---|
| `gradual_drift` | OLS slope of trust scores < −0.05 per reading |
| `random_dropout` | Trust score stdev > 0.20 over the window |
| `stuck_at` | Key field range (max − min) < 0.01 across the window |
| `burst_loss` | 3+ consecutive `delivered=False` records |

```python
history = SensorTrustHistory(window=20)
result = history.update(sensor_id, trust_score, record)
if result.fault_detected:
    print(result.fault_pattern, result.evidence)
```

---

## 10. Statistical evaluation

### Wilcoxon test (evaluation/wilcoxon.py)

Pure-Python paired Wilcoxon signed-rank test. No scipy or statsmodels required.
Uses average-rank tie handling and a normal approximation p-value.

```python
from evaluation.wilcoxon import wilcoxon_signed_rank
W, p, effect_r = wilcoxon_signed_rank(b0_latencies, b5_latencies)
# p < 0.05 → statistically significant difference
# effect_r = |Z| / sqrt(n)  (small 0.1, medium 0.3, large 0.5)
```

### Multi-seed statistical evaluation (evaluation/statistical_eval.py)

```bash
# Run all baselines over 30 seeds, save JSON
python -m evaluation.statistical_eval --seeds 30 --output stats.json

# Compare B0 vs B5 and B2 vs B5 specifically
python -m evaluation.statistical_eval --seeds 10 --compare B0,B5 B2,B5
```

Output JSON structure:
```json
{
  "seeds": [1, 2, ..., 30],
  "aggregated": {
    "B5": {
      "n_runs": 30,
      "mean_latency_ms": {"mean": 18.2, "std": 0.9, "ci95_lo": 17.8, "ci95_hi": 18.6}
    }
  },
  "wilcoxon_tests": {
    "B0_vs_B5": {
      "mean_latency_ms": {"W": 0, "p_value": 0.000001, "significant_05": true, "effect_size_r": 0.92}
    }
  }
}
```

---

## 11. Federated learning

### Why federated learning here?

In the real deployment, each fog server manages a group of sensor devices that
belong to one farm or one region. Farms cannot share their raw data for privacy
and bandwidth reasons. FL allows each fog server to train a local TinyML update
model and contribute only compressed weight updates to the cloud aggregator.

### Architecture

```
Cloud aggregator (fl_runner.py)
  │  sends global_params
  ▼
Client 1 trainer   Client 2 trainer   Client 3 trainer   ...
  │  trains on       │  trains on       │  trains on
  │  local data      │  local data      │  local data
  ▼                  ▼                  ▼
  params + n_train → FedAvg aggregator → updated global_params
```

### Components

**MiniLogisticRegression (federated/model.py)**

A from-scratch multi-class logistic regression:
- Softmax output over `N_CLASSES = 8` (the eight agricultural scenarios).
- Fixed input vector: 8 sensor features in `FEATURE_KEYS` order.
- Mini-batch SGD with L2 regularisation.
- `get_params() / set_params(params)` for serialisation (FedAvg-compatible).

**Local trainer (federated/trainer.py)**

```python
result = train_local(
    client_dir=Path("federated_output/synthetic/client-01"),
    global_params=global_params,  # None for round 0
    epochs=20, lr=0.05,
)
# result["params"]    → updated weights ready for FedAvg
# result["n_train"]   → sample count for weighted averaging
# result["val_acc"]   → validation accuracy
```

**FedAvg aggregator (federated/aggregator.py)**

```python
from federated.aggregator import fedavg
global_params = fedavg([
    {"params": client1_params, "n_train": 150},
    {"params": client2_params, "n_train": 80},
])
# Weighted average: w_i = n_train_i / sum(n_train)
```

`scaffold_correction(global, clients, lr_global)` applies a drift correction
before averaging, which helps when client data distributions differ widely.

**FL runner (federated/fl_runner.py)**

```bash
# Build dataset first
python -m federated.dataset_builder --source synthetic \
    --clients 4 --seed 5 --output federated_output/synthetic

# Train 10 rounds of FedAvg
python -m federated.fl_runner --data federated_output/synthetic --rounds 10

# Save full results including weights
python -m federated.fl_runner --data federated_output/synthetic \
    --rounds 20 --lr 0.05 --output fl_results.json
```

After each round the global model is evaluated on all clients' test sets.
The output includes `rounds_history` (per-round train/val accuracy),
`global_test_acc`, and `global_test_macro_f1`.

### Dataset preparation (federated/dataset_builder.py)

`build_synthetic_federated_dataset(output_dir, client_count=4, seed=5)` generates
a reproducible multi-zone telemetry dataset and partitions it by device ownership
into per-client `train.jsonl`, `validation.jsonl`, `test.jsonl` files.

`build_crop_proxy_federated_dataset(archive, output_dir, ...)` partitions the
bundled crop recommendation CSV using a Dirichlet distribution to create non-IID
label skew across clients (simulating that different farms grow different crops).

---

## 12. Zone context system (context/)

### ZoneContextManager (context/zone_state.py)

Maintains a deque (default 256 entries) of delivered `TelemetryRecord` objects
per zone. On `snapshot(zone_id)` it computes a `ZoneContext` object with:

- Per-field statistics: mean, min, max, latest, linear slope per hour.
- Agricultural derived features:
  - **Soil-water deficit**: `max(0, field_capacity − current_moisture)`.
  - **VPD (vapour-pressure deficit)**: `SVP(T) × (1 − RH/100)` in kPa.
- Cross-sensor anomaly detection: if two sensors in the same zone disagree by
  more than 2× the inter-device spread threshold, an anomaly finding is raised.

The zone context snapshot is attached to every pipeline message under `zone_context`
and is available to both `CriticalityAgent` and `DecisionAgent`.

### MultimodalFusionAgent (context/multimodal_fusion.py)

Accepts optional image features, text notes, or spectral data alongside the
sensor readings. Produces a `semantic_summary` string that the `CriticalityAgent`
can use as additional evidence. Returns `available=False` and an empty summary
when no multimodal inputs are provided.

---

## 13. Safety and enforcement

### Decision safety gates

For automatic actuation (`act_locally`) ALL of the following must hold:

```
trust_level == HIGH
AND situation is NOT critical
AND sanity_score >= 0.90
AND no failed sensor fields
AND action is in ACTION_WHITELIST
AND policy explicitly permits the action
```

The policy check is enforced twice: once by `DecisionAgent` (intelligence layer)
and once by `ActionHandler` (enforcement layer). This dual check means a
misconfigured agent cannot bypass the hardware safety barrier.

### Security audit chain (support_services.py)

Every pipeline run appends a structured entry to `logs/security_audit_chain.jsonl`:
sensor ID, event type (validation passed, rejected, action authorised), HMAC
signature validity, and timestamp. This creates a tamper-evident log of every
decision made by the system.

### NTN-aware routing (agents/decision_agent.py)

When `link_state == "offline"` and trust is MEDIUM, the agent avoids escalating
to a cloud that is unreachable:

```
link_state="offline", trust=MEDIUM → decision="validate", source="rule"
link_state="ntn",     trust=MEDIUM → decision="validate" (high-cost link warning)
```

---

## 14. Infrastructure

### Docker Compose (development)

```bash
docker compose up -d          # Redpanda + Console + fog-agent
docker compose ps             # check status
# Console UI at http://localhost:8080
```

Services:
- `redpanda` — Kafka-compatible broker, dual listener (internal 29092 / external 9092)
- `redpanda-console` — Web UI at port 8080
- `fog-agent` — runs `main.py --kafka --offline` connected to Redpanda

### Docker Compose (production)

```bash
docker compose -f docker-compose.production.yml up -d
```

Additional services:
- `postgres` — PostgreSQL 16; schema from `db/postgres_schema.sql`
- `cloud-storage-consumer` — persists all Kafka events to PostgreSQL and SQLite
- `digital-twin-service` — advances digital twin from fog decisions
- `governance-consumer` — logs policy enforcement events
- `dashboard` — HTTP dashboard at port 8050
- `fog-agent` — production fog pipeline with restart policy
- `backup` — one-shot SQLite backup job

### Environment variables (config.py)

All integration settings read from environment variables with safe defaults:

| Variable | Default | Description |
|---|---|---|
| `CLOUD_SYNC_MODE` | `local_queue` | `kafka`, `http`, or `local_queue` |
| `CLOUD_KAFKA_BOOTSTRAP` | (none) | Kafka bootstrap address |
| `ACTUATOR_MODE` | `local_queue` | `http`, `mqtt`, or `local_queue` |
| `CRITICALITY_MODE` | `local_first` | `local_first` or `remote` |
| `CRITICALITY_ENABLE_REMOTE_FALLBACK` | `false` | Enable LLM fallback |
| `DB_BACKEND` | `sqlite` | `sqlite` or `postgresql` |
| `FARM_ID` | `demo-farm` | Farm identifier for digital twin |
| `TWIN_SIMULATION_STEP_MINUTES` | `10` | Twin step interval |
| `SECURITY_HMAC_SECRET` | `dev-fog-secret` | HMAC key for sensor identity |

---

## 15. Testing and quality

### Running tests

```bash
python -m unittest discover -s tests -v
# Result: 21 tests passed
```

Tests cover validation agents, trust scoring, zone context, baseline simulation,
and the Wilcoxon test implementation.

### Quick end-to-end smoke test

```bash
# Offline fog run (no API key needed)
python main.py --offline --limit 10

# B5 baseline with digital twin
python -c "
from simulation.baselines import BaselineSimulator, Baseline
from simulation.generator import SyntheticTelemetryGenerator, SimulationConfig
from simulation.network_model import MarkovConnectivityModel
from digital_twin.simulator import DigitalTwinEngine

config = SimulationConfig(seed=1, duration_minutes=60)
records = SyntheticTelemetryGenerator(config, [], [], MarkovConnectivityModel(1)).generate()
twin = DigitalTwinEngine()
sim = BaselineSimulator(Baseline.B5_FULL_SYSTEM, twin=twin)
outcomes, dash = sim.run_with_twin(records)
print(f'{len(outcomes)} outcomes, twin zones: {[z[\"zone_id\"] for z in dash[\"zones\"]]}')
"

# What-if analysis
python -m tools.what_if --zone zone-1 --scenario irrigation --horizon 3

# Multi-seed stats (5 seeds for speed)
python -m evaluation.statistical_eval --seeds 5 --baselines B0 B5
```

---

## 16. Key design decisions and trade-offs

### Why SimPy for the baselines?

SimPy is a discrete-event simulation library. Using real `asyncio` or threading
to simulate 50 seeds × 6 baselines × 1000 records would be impractical in a
research setting. SimPy allows accurate modelling of concurrency (multiple
records in-flight simultaneously), network delays, and processing queues without
real infrastructure, and the results are fully reproducible from a seed.

### Why pure-Python for statistics and ML?

The evaluation modules (`wilcoxon.py`, `trust_roc.py`, `model.py`) have zero
external ML or statistics dependencies. This matters for edge deployments where
scipy, statsmodels, or scikit-learn may not be installable. It also makes the
statistical logic transparent and auditable.

### Why frozen dataclasses for DecisionOutcome?

Immutability ensures no simulation step accidentally modifies a past outcome.
The twin risk index is attached using `dataclasses.replace(outcome, twin_risk_index=...)`,
which creates a new instance rather than mutating the original.

### Why lazy-init for KafkaProducer?

`KafkaProducer()` blocks until it establishes a connection to the broker. If the
pipeline imports `cloud_sync` before Redpanda is ready (e.g., during tests or
fast startup), a module-level producer would fail immediately. Lazy init defers
the connection to the first actual publish call.

### Why Redpanda instead of Apache Kafka?

Redpanda is Kafka-API-compatible but is a single binary (no JVM, no ZooKeeper).
It starts in under 2 seconds, uses less than 100 MB RAM in dev mode, and runs the
same `kafka-python` client code. The dual-listener setup
(`INTERNAL://redpanda:29092, EXTERNAL://localhost:9092`) is required because
Docker containers use the internal Docker DNS name `redpanda`, while host Python
processes use `localhost`.

---

## 17. Limitations and honest caveats

| Component | Limitation |
|---|---|
| TinyML classifier | The synthetic generator uses the same thresholds as the classifier, making B1 / B5 F1 look artificially high. Real field accuracy requires field-trained models. |
| LLM cost | `$0.002` per B3 call is a proxy for GPT-4 pricing. Actual cost depends on the provider, model, and prompt length. |
| Energy model | Millijoule values are literature-derived proxies, not measured. Real MCU power depends on clock speed, sleep state, and antenna type. |
| NTN latency | 650 ms is typical for geostationary satellite (GEO). LEO constellations (Starlink) achieve 20–40 ms. |
| Federated learning | The FL model is trained on synthetic data produced by the same generator used for evaluation. Performance on real multi-farm data is unknown. |
| Hardware integration | Raspberry Pi firmware, real actuator wiring, and TinyML model deployment are not implemented in this repository. |
| Calibration | `CalibrationProfile` parameters (evapotranspiration coefficients, drainage thresholds) are defaults, not calibrated to a specific farm. |

---

## 18. File map — where everything lives

```
AgenticAiFog/
│
├── main.py                         Entry point; CLI flags; dataset loading
├── pipeline.py                     FogPipeline: 6 agents + enforcement
├── config.py                       All configuration constants and env vars
├── models.py                       TrustLevel, CriticalityScenario enums
├── contracts.py                    PipelineContext TypedDict
│
├── agents/
│   ├── data_validation_agent.py    Agent 1: schema + identity
│   ├── timestamp_agent.py          Agent 2: freshness + UTC
│   ├── trust_score_agent.py        Agent 3: composite trust score
│   ├── value_sanity_agent.py       Agent 4: physical range checks
│   ├── context_manager_agent.py    Agent 5a: zone rolling context
│   ├── criticality_agent.py        Agent 5b: scenario classification
│   └── decision_agent.py           Agent 6: act/validate/escalate/reject
│
├── context/
│   ├── zone_state.py               ZoneContextManager + ZoneContext
│   ├── rolling_features.py         Slope, VPD, soil-water deficit
│   ├── anomaly_detection.py        Cross-sensor anomaly detection
│   └── multimodal_fusion.py        Optional image/text/spectral fusion
│
├── simulation/
│   ├── telemetry_schema.py         TelemetryRecord canonical message
│   ├── generator.py                Synthetic event + fault generator
│   ├── network_model.py            Markov connectivity model
│   ├── baselines.py                B0–B5 SimPy baselines; energy model
│   ├── experiment_metrics.py       summarize_outcomes() with all metrics
│   ├── experiment_runner.py        CLI for multi-seed runs
│   ├── fog_adapter.py              TelemetryRecord → FogPipeline bridge
│   └── zone_pipeline.py            ZoneFogPipeline with twin support
│
├── evaluation/
│   ├── trust_roc.py                Trust ROC-AUC (pure Python)
│   ├── trust_history.py            Fault detection from trust trajectory
│   ├── wilcoxon.py                 Paired Wilcoxon signed-rank test
│   └── statistical_eval.py         Multi-seed stats + CI + pairwise tests
│
├── digital_twin/
│   ├── entities.py                 FarmEntity, ZoneEntity, SensorEntity ...
│   ├── process_models.py           Soil, crop, equipment process models
│   ├── simulator.py                DigitalTwinEngine: step/simulate/what_if
│   ├── calibration.py              CalibrationProfile; parameter fitting
│   ├── contracts.py                FogSummaryContract schema validation
│   ├── repositories.py             SQLiteRepositories for persistence
│   ├── feedback.py / feedback_store.py  Human feedback collection
│   ├── optimization.py             IrrigationOptimizer
│   ├── synthetic_events.py         Rare-event dataset generation
│   └── connectivity.py             Kafka envelope helpers for twin topics
│
├── federated/
│   ├── model.py                    Pure-Python multi-class logistic regression
│   ├── trainer.py                  Local training step
│   ├── aggregator.py               FedAvg + SCAFFOLD aggregator
│   ├── fl_runner.py                Multi-round FL orchestrator + CLI
│   └── dataset_builder.py          Per-client JSONL dataset preparation
│
├── services/
│   └── digital_twin_service.py     Kafka consumer advancing the twin
│
├── tools/
│   ├── setup_topics.py             Create all Kafka topics
│   ├── what_if.py                  Digital twin what-if scenario CLI
│   ├── dashboard.py                HTTP dashboard (Dash / Flask)
│   ├── cloud_storage_consumer.py   Persist Kafka events to DB
│   ├── governance_consumer.py      Policy enforcement logging
│   └── backup_sqlite.py            SQLite backup job
│
├── cloud_sync.py                   KafkaPublisher, HTTP publisher, local queue
├── cloud_interface.py              CloudInterface: escalation + model updates
├── action_handler.py               ActionHandler: actuator + cloud routing
├── trust_scorer.py                 Standalone trust utility
├── anomaly_detector.py             MultiLevelAnomalyDetector
├── decision_cache.py               LRU cache for DecisionAgent
├── metrics.py                      PipelineMetrics with per-agent timing
├── logger.py                       FogLogger: structured JSON decision log
│
├── docker-compose.yml              Dev stack: Redpanda + Console + fog-agent
├── docker-compose.production.yml   Full stack: + Postgres + services + dashboard
├── Dockerfile                      Python 3.12 image for all services
│
├── data/archive.zip                Bundled crop recommendation CSV
├── state/                          SQLite DBs, decision cache, rule store
├── logs/                           Decision JSON log, audit chain
│
├── READMEWHATWEDID.md              Project status and missing-work tracker
├── WHAT_WE_ADDED.md                Session work log
├── PROJECT_OVERVIEW.md             This file
├── KAFKA_FIXES.md                  Kafka bug fixes documentation
└── ARCHITECTURE_REVIEW.md          High-level architecture review notes
```

---

## 19. How to run the full stack from scratch

```bash
# 1. Install Python dependencies
pip install -r requirements.txt -r requirements-cloud.txt

# 2. Start Kafka + UI (dev)
docker compose up -d

# 3. Create Kafka topics
python -m tools.setup_topics --bootstrap localhost:9092

# 4. Run the fog agent offline (no API key needed)
python main.py --offline --limit 20

# 5. Run with Kafka publishing
python main.py --kafka --kafka-bootstrap localhost:9092

# 6. Run a B5 simulation (50 records)
python -m simulation.experiment_runner --baseline B5 --seed 7

# 7. Run all baselines over 5 seeds with output
python -m simulation.experiment_runner --baseline all \
    --seeds 1 2 3 4 5 --output results.json

# 8. Build federated dataset and train
python -m federated.dataset_builder --source synthetic \
    --clients 4 --seed 5 --output federated_output/synthetic
python -m federated.fl_runner --data federated_output/synthetic --rounds 10

# 9. What-if scenario analysis
python -m tools.what_if --zone zone-1 --scenario irrigation --horizon 3

# 10. Statistical evaluation (30 seeds)
python -m evaluation.statistical_eval --seeds 30 --output stats.json

# 11. Full production stack
docker compose -f docker-compose.production.yml up -d
```
