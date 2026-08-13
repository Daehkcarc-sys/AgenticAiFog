# What We Added — Session Work Log

This document describes everything added to the `fix/kafka-working` branch
across two work sessions. It is a companion to `READMEWHATWEDID.md`, which
tracks the overall project status.

---

## Session 1 — Kafka fixes and missing architecture items

### Kafka / Redpanda stack (fixes)

**Problem.** The original `docker-compose.yml` had a single-listener Redpanda
setup. Services inside Docker could reach port 29092, but host-side Python
clients needed port 9092, and Redpanda Console had no broker address set.
Additionally, a local `kafka/` directory shadowed the installed `kafka-python`
package, causing `ModuleNotFoundError` on every import.

**Files changed.**

| File | What changed |
|---|---|
| `docker-compose.yml` | Dual-listener `INTERNAL://redpanda:29092,EXTERNAL://localhost:9092`; healthcheck; Console `KAFKA_BROKERS`; `auto_create_topics_enabled=true` |
| `cloud_sync.py` | `KafkaPublisher` rewritten with lazy-init singleton producer; `build_cloud_publisher()` reads env vars at call time (not import time) |
| `main.py` | `--kafka` and `--kafka-bootstrap` CLI flags; sets env vars before pipeline construction |
| `requirements.txt` | Added `kafka-python>=2.0.2` |
| `tools/setup_topics.py` | New — creates all 10 Kafka topics via `KafkaAdminClient`; supports `--list`, `--dry-run` |
| `KAFKA_FIXES.md` | New — documents all 6 bugs fixed |

### Missing architecture items (from `READMEWHATWEDID.md` section 9)

**Item 1 — `simulation/fog_adapter.py` (new)**

`telemetry_to_pipeline_message(record: TelemetryRecord) -> dict` bridges the
simulation's rich `TelemetryRecord` schema to the flat dict that `FogPipeline.run()`
expects. Maps `tinyml_class` to one of the seven action strings; passes through
link state, fault labels, and zone ID.

**Items 2–5 — `simulation/zone_pipeline.py` (new) + `pipeline.py` + `agents/decision_agent.py`**

`ZoneFogPipeline` wraps `FogPipeline` with a `ZoneContextManager`. For each
arriving `TelemetryRecord`:
1. The zone manager is updated with the new readings.
2. A `ZoneContext` snapshot (means, slopes, VPD, cross-sensor anomalies) is
   attached to the message as `zone_context`.
3. `FogPipeline.run()` receives `link_state` and `zone_id` in the payload.
4. `DecisionAgent._try_rules()` now checks `link_state`; when offline or on NTN
   it returns a local-validation decision instead of escalating to the cloud.

**Items 8 and 16 — `simulation/baselines.py` (extended)**

Four new baselines added: `B1_EDGE_ONLY` (5 ms TinyML-only), `B3_DIRECT_LLM`
(200 ms simulated LLM on top of cloud RTT), `B4_TRUST_FOG` (trust-gated static
fog), `B5_FULL_SYSTEM` (trust + zone context + NTN routing + optional twin).

**Items 13–14 — `evaluation/trust_history.py` (new)**

`SensorTrustHistory` maintains a rolling window of trust scores per sensor.
Detects four fault patterns purely from the trajectory, with no access to ground
truth:
- `gradual_drift` — OLS slope < −0.05 per reading
- `random_dropout` — trust stdev > 0.20
- `stuck_at` — key field range < 0.01 across the window
- `burst_loss` — three or more consecutive undelivered records

**Item 15 — `evaluation/trust_roc.py` (new)**

`compute_roc_auc(samples)` evaluates trust scores against ground-truth fault
labels using a trapezoidal AUC over the ROC curve. `samples_from_records(records)`
builds the sample list directly from `TelemetryRecord` objects.

**Items 17–20 — `evaluation/wilcoxon.py` + `evaluation/statistical_eval.py` (new)**

`wilcoxon_signed_rank(x, y)` is a pure-Python paired Wilcoxon signed-rank test
with average-rank tie handling and normal-approximation p-value. Requires no
scipy or statsmodels.

`statistical_eval.py` runs every baseline over 30–50 seeds, computes mean, std,
and 95 % CI for each metric, and applies pairwise Wilcoxon tests. CLI:

```
python -m evaluation.statistical_eval --seeds 30 --output stats.json
python -m evaluation.statistical_eval --seeds 5 --compare B0,B5 B2,B5
```

---

## Session 2 — Digital twin bridge, FL, energy model, Docker, what-if CLI

### 1 — Digital twin ↔ simulation bridge

**`simulation/baselines.py`**

`BaselineSimulator` now accepts an optional `twin: DigitalTwinEngine`. In the
B5 path, after every decision (accept, reject, or escalate), the simulator calls
`twin.apply_fog_summary()` with a `FogSummaryContract`-compatible payload. The
resulting zone risk index is stored on the `DecisionOutcome` via
`dataclasses.replace(outcome, twin_risk_index=zone.risk_index)`.

`run_with_twin(records)` returns `(outcomes, twin.dashboard_state())` so callers
can inspect the full twin state after a simulated run.

**`simulation/zone_pipeline.py`**

`ZoneFogPipeline.__init__` now accepts `twin: DigitalTwinEngine | None`. After
each `FogPipeline.run()` call the pipeline feeds the fog outcome back into the
twin via `apply_fog_summary()`. `twin_dashboard()` returns the current twin state.

### 2 — B2 zone-level fusion + B0 raw-stream multiplier

**`simulation/baselines.py`**

`_ZoneWindow` is a rolling buffer (deque, default 10 readings) per zone. It is
updated at record-arrival time inside `_process()`. B2 calls
`classify_with_zone(record, zone_means)` instead of `classify(record)`, blending
each individual reading with the zone running average before applying rules.
`BaselineSimulator(zone_fusion=False)` disables the window.

`BaselineSimulator(high_freq_factor=N)` multiplies the B0 payload bytes by N,
simulating a scenario where the edge device streams N raw samples per
aggregation interval instead of a single summary.

`StaticEventClassifier.classify_with_zone(record, zone_means)` merges values:
`merged[k] = (individual + zone_mean) / 2` for each field present in both, then
runs the same threshold rules on the merged dict.

### 3 — Component-level energy model + LLM cost

**`simulation/baselines.py`**

New fields on `DecisionOutcome`:

| Field | Type | Description |
|---|---|---|
| `edge_energy_mj` | float | Millijoules at the edge device (TinyML inference) |
| `fog_energy_mj` | float | Millijoules at the fog node (rule evaluation / trust scoring) |
| `cloud_energy_mj` | float | Millijoules at the cloud server + transmission |
| `llm_cost` | float | LLM API cost proxy in USD |
| `twin_risk_index` | float \| None | Digital twin zone risk index (B5 only) |

Energy proxy values used:
- B1 edge-only: 0.5 mJ (TinyML MCU inference)
- B2 static fog: 2.0 mJ (rule evaluation)
- B4 trust fog: 0.5 mJ edge + 3.0 mJ fog
- B5 local path: 0.5 mJ edge + 5.0 mJ fog (zone context + trust + rules)
- B5 cloud escalation: same fog overhead + 20 mJ cloud + transmission
- B0 / B3 cloud: 20 mJ cloud processing + transmission energy
- Transmission energy: 1 μJ/byte terrestrial, 50 μJ/byte NTN
- LLM cost: $0.002 USD per B3 call (GPT-4 pricing proxy)

**`simulation/experiment_metrics.py`**

`summarize_outcomes()` now returns:
- `edge_energy_mj`, `fog_energy_mj`, `cloud_energy_mj` — per-component totals
- `total_energy_mj` — sum of all three
- `llm_cost_usd` — total USD for B3 LLM calls
- `twin_mean_risk_index` — mean twin risk index for B5 outcomes

### 4 — Federated learning training pipeline

**`federated/model.py`**

`MiniLogisticRegression` — pure-Python multi-class logistic regression.
- No external ML library required.
- Mini-batch SGD with cross-entropy loss and softmax output.
- L2 regularisation.
- Fixed 8-feature input (`FEATURE_KEYS`) and 8-class output (`LABEL_ORDER`)
  shared across all clients so weight vectors are compatible for FedAvg.
- `get_params()` / `set_params(params)` for weight serialisation.

Helper functions: `load_jsonl(path)`, `accuracy()`, `macro_f1()`, `row_to_xy()`.

**`federated/trainer.py`**

`train_local(client_dir, global_params, epochs, lr, ...)` trains one client.
Loads `train.jsonl`, optionally loads `validation.jsonl` for metrics, returns a
dict with `params`, `n_train`, `train_acc`, `val_acc`, `val_macro_f1`.

**`federated/aggregator.py`**

`fedavg(client_results)` — weighted average of weight dicts, weights proportional
to each client's `n_train`. Implements Algorithm 1 from McMahan et al. (2017).

`scaffold_correction(global_params, client_results, lr_global)` — heuristic
global update with drift correction (simplified SCAFFOLD variant).

**`federated/fl_runner.py`**

`run_federated_learning(data_dir, rounds, client_fraction, ...)` — full
multi-round FedAvg orchestrator:
1. Discover client directories (any folder with `train.jsonl`).
2. Each round: randomly select `client_fraction` clients, run `train_local()`,
   aggregate with `fedavg()`.
3. After all rounds: evaluate the global model on all clients' test sets.
4. Return `rounds_history`, `final_params`, `global_test_acc`, `global_test_macro_f1`.

CLI:
```
python -m federated.fl_runner --data federated_output/synthetic --rounds 10
python -m federated.fl_runner --data federated_output/synthetic --rounds 5 \
    --clients 2 --lr 0.05 --output fl_results.json
```

### 5 — Fog agent Docker services

**`docker-compose.yml`** (development)

New `fog-agent` service:
```yaml
fog-agent:
  build: .
  command: python main.py --kafka --kafka-bootstrap redpanda:29092 --offline --limit 50
  environment:
    CLOUD_SYNC_MODE: kafka
    CLOUD_KAFKA_BOOTSTRAP: redpanda:29092
  depends_on:
    redpanda:
      condition: service_healthy
```
Starts automatically when `docker compose up` is run in dev. The `--offline` flag
keeps the agent running without an LLM API key.

**`docker-compose.production.yml`**

New `fog-agent` service with `restart: unless-stopped` and `env_file:
.env.production`. The production agent connects to the internal Redpanda broker
on `redpanda:9092` without the `EXTERNAL` listener.

### 6 — What-if scenario CLI (`tools/what_if.py`)

Wraps `DigitalTwinEngine.what_if()` in a command-line interface.

```
# Simulate drought on zone-1 for 3 × 30-minute steps
python -m tools.what_if --zone zone-1 --scenario irrigation --horizon 3

# Load live twin state from SQLite database
python -m tools.what_if --zone zone-1 --scenario heat_stress \
    --state state/digital_twin.db

# List available scenarios
python -m tools.what_if --list-scenarios
```

Output JSON includes `baseline_risk`, `projected_risk`, `risk_delta`,
`recommendation`, per-step `trace`, and the projected zone state (soil moisture,
crop disease/heat/pest risks, dynamic state).

Available scenarios: `irrigation`, `disease_risk`, `heat_stress`,
`equipment_failure`, `resource_allocation`.

---

## Session 3 — Real federated tomato yield model integration

### Federated yield predictor (`federated/yield_predictor.py`)

The `final_fog_yield_model1.zip` produced by the FedAvg training phase (from
the `main` branch) was extracted into `federated/yield_model/`. The following
artifacts are now part of the repository:

| File | Purpose |
|---|---|
| `global_yield_model.pt` | PyTorch MLP weights (FedAvg global model) |
| `imputer.joblib` | sklearn SimpleImputer for missing-feature handling |
| `scaler.joblib` | sklearn StandardScaler (fit on all 65 features) |
| `model_config.json` | Architecture: `{input_dim: 65, hidden_dims: [32, 16], dropout: 0.1}` |
| `model_card.json` | FedAvg_v4, MAE=10.999 t/ha, R²=0.62 over 30 seeds |
| `preprocessor_schema.json` | 65 feature names, `target_mean=86.303`, `target_std=24.328` |
| `fog_request_example.json` | Example Fog request envelope |
| `fog_response_example.json` | Expected response: `{"predicted_yield": 71.63, "unit": "t/ha", ...}` |
| `results.json` | Detailed evaluation results for seed 104 |
| `README.md` | FL phase documentation |

**`federated/yield_predictor.py`** wraps the PyTorch model with:

- `FogYieldPredictor(model_dir, device)` — loads model + preprocessors on init.
- `predict(features: dict) -> dict` — builds a 65-element feature vector (NaN
  for missing features, then imputed), runs sklearn preprocessing + PyTorch
  inference, denormalises using `target_mean` / `target_std`, and returns:
  ```json
  {
    "predicted_yield": 71.6,
    "unit": "t/ha",
    "source": "federated_global_yield_model",
    "model_version": "FedAvg_v4",
    "confidence_note": "mean MAE ≈ 11.0 t/ha over 30 seeds"
  }
  ```
- `handle_fog_request(request: dict) -> dict` — processes the full Fog
  envelope (`zone_id`, `timestamp`, `features`) and adds `zone_id` /
  `request_timestamp` to the response.
- `feature_names` property — returns the list of 65 expected input features.
- `model_card` property — returns the parsed `model_card.json`.

**`requirements-yield.txt`** — optional dependencies: `torch>=2.0`,
`scikit-learn>=1.3`, `joblib>=1.3`. Install only when the yield predictor is
used.

**Model architecture** (`YieldMLP`):

```
Input(65) → Linear(65→32) → BN → ReLU → Dropout(0.1)
          → Linear(32→16) → BN → ReLU → Dropout(0.1)
          → Linear(16→1)
```

**Training details:** 9 year-based Fog clients (Carucci industrial-tomato
dataset, 1978–2022); FedAvg with weighted averaging proportional to
`n_train`; target z-score normalized (mean=86.30 t/ha, std=24.33 t/ha);
30-seed repeated evaluation: **MAE ≈ 11.0 t/ha, R² ≈ 0.62**.

---

## Files added or modified across both sessions

| Path | Status | Description |
|---|---|---|
| `docker-compose.yml` | Modified | Dual listener, healthcheck, fog-agent service |
| `docker-compose.production.yml` | Modified | fog-agent service, app-logs volume |
| `requirements.txt` | Modified | `kafka-python>=2.0.2` |
| `main.py` | Modified | `--kafka`, `--kafka-bootstrap` CLI flags |
| `cloud_sync.py` | Modified | Lazy KafkaProducer, runtime env-var reads |
| `pipeline.py` | Modified | zone_context, link_state, zone_id in context |
| `agents/decision_agent.py` | Modified | NTN/offline routing rules |
| `simulation/baselines.py` | Modified | B1–B5, zone fusion, energy model, twin bridge |
| `simulation/experiment_metrics.py` | Modified | Energy, LLM cost, twin risk in summarize_outcomes |
| `simulation/experiment_runner.py` | Modified | Multi-seed runner, B0–B5 choices |
| `simulation/zone_pipeline.py` | Modified | Optional twin parameter |
| `simulation/fog_adapter.py` | New | TelemetryRecord → FogPipeline adapter |
| `tools/setup_topics.py` | New | Kafka topic setup CLI |
| `tools/what_if.py` | New | Digital twin what-if CLI |
| `evaluation/__init__.py` | New | Evaluation package |
| `evaluation/trust_roc.py` | New | Trust ROC-AUC |
| `evaluation/trust_history.py` | New | Sensor fault detection from trust history |
| `evaluation/wilcoxon.py` | New | Pure-Python Wilcoxon signed-rank test |
| `evaluation/statistical_eval.py` | New | Multi-seed stats, CI, pairwise tests |
| `federated/__init__.py` | Modified | Re-exports FL utilities |
| `federated/model.py` | New | Pure-Python logistic regression |
| `federated/trainer.py` | New | Local FL training step |
| `federated/aggregator.py` | New | FedAvg + SCAFFOLD-style correction |
| `federated/fl_runner.py` | New | Multi-round FL orchestrator |
| `federated/yield_predictor.py` | New | PyTorch MLP yield inference wrapper |
| `federated/yield_model/` | New | Global yield model artifacts (9 files) |
| `final_fog_yield_model1.zip` | New | Source zip from main branch (FL phase output) |
| `requirements-yield.txt` | New | Optional deps: torch, scikit-learn, joblib |
| `KAFKA_FIXES.md` | New | Documents 6 Kafka bugs |
| `WHAT_WE_ADDED.md` | New | This file |
| `READMEWHATWEDID.md` | Modified | Status table and section 9 updated |
| `PROJECT_OVERVIEW.md` | Modified | Section 20 added: real FL yield model |
| `README.md` | Modified | Added Lemon and Soni-KR to authors |
