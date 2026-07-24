# Agentic AI Fog - Cloud/Fog/Edge Agricultural Digital Twin

This repository contains the integrated fog-agentic pipeline plus the local/demo cloud stack for a trust-oriented cloud-fog-edge agricultural digital twin.

The project now has two runnable modes:

- **Local/default mode:** no Docker or external services required. Uses local queues, JSON logs, SQLite, and deterministic fallbacks.
- **Production-like demo mode:** Docker Compose stack with Redpanda/Kafka, PostgreSQL, cloud consumers, a separate digital twin service, governance consumer, and repository-backed dashboard/API.

The code is ready for teammates to continue ML, Kafka, edge/hardware, and digital-twin calibration work without reverse-engineering the full project.

---

## Current Owners

| Area | Owner |
|---|---|
| Agentic context, criticality, documentation | Zaaa / Aziza |
| Agentic decision, safety gates, pipeline stability | Lion |
| ML scenario modeling and model evaluation | Sonic + Sarra |
| Kafka/cloud synchronization | Limon |
| Edge/TinyML/hardware/actuators | 3otri |
| Digital twin production ownership | TBD |

---

## Current Architecture

```text
Edge / Physical Twin
  Sensors, TinyML, field gateway, actuators
        |
        v
Fog Node
  Trust Layer        -> validation, timestamp, trust score, sanity checks
  Context Layer      -> rolling history, features, anomalies, multimodal placeholder
  Decision Layer     -> local-first criticality, rule/cache/LLM/cloud decision
  Enforcement Layer  -> PEP, actuator adapters, audit/logs, cloud sync
        |
        v
Kafka / Cloud Sync
  Redpanda/Kafka topics, retry, dead-letter, governance events
        |
        v
Cloud Digital Twin Services
  PostgreSQL/SQLite repositories, digital twin service, dashboard/API,
  feedback labels, calibration profiles, policy/model update consumer
```

Production target for this project phase:

```text
Fog nodes -> Kafka/Redpanda -> separate Python digital-twin-service -> PostgreSQL/TimescaleDB target schema -> dashboard/API
```

SQLite remains the default local fallback so all teammates can run tests without installing PostgreSQL.

---

## What Is Implemented

### Fog Pipeline

Main file: `pipeline.py`

Implemented flow:

```text
incoming message
  -> DataValidationAgent
  -> TimestampAgent
  -> TrustScoreAgent
  -> ValueSanityAgent
  -> ContextManagerAgent
  -> MultiLevelAnomalyDetector
  -> MultimodalFusionAgent placeholder
  -> CriticalityAgent
  -> DecisionAgent
  -> ActionHandler / PEP
  -> logs, metrics, audit, cloud sync
```

Implemented components:

- Trust layer with schema validation, timestamp freshness, trust scoring, sanity checks.
- Context layer with sliding history, rolling averages, slopes, variance, derived features, semantic summaries.
- Multi-level anomaly detection: physical, statistical, and domain-rule based.
- Per-decision explanation trace in accepted logs/cloud summaries.
- Multimodal fusion placeholder for drone/satellite metadata and precomputed visual features.
- Local-first criticality classifier for the eight scenarios.
- Optional remote Groq fallback only for configured ambiguous criticality cases.
- Decision cache with exact and similarity matching.
- Policy enforcement and actuator routing.
- Local queue, HTTP, MQTT, and command actuator adapter foundations.

### Cloud / Kafka / Storage

Implemented files:

- `cloud_events.py`
- `cloud_sync.py`
- `cloud_interface.py`
- `tools/cloud_storage_consumer.py`
- `tools/governance_consumer.py`
- `docker-compose.yml`
- `docker-compose.production.yml`

Implemented features:

- Versioned cloud event envelope.
- Kafka/local topics:
  - `sensor-data`
  - `trust-events`
  - `fog-decisions`
  - `critical-events`
  - `model-updates`
  - `policy-updates`
  - `fog-dead-letter`
  - `twin-state`
  - `twin-sync`
  - `twin-command`
- Local queue, HTTP, and Kafka publisher adapters.
- Retry/backoff and dead-letter fallback.
- Model update metadata store and rollback hooks.
- Governance consumer applies `policy_update` to `LocalRuleStore` and `model_update` to `ModelUpdateStore`.

### Digital Twin

Implemented files:

- `digital_twin/entities.py`
- `digital_twin/contracts.py`
- `digital_twin/simulator.py`
- `digital_twin/process_models.py`
- `digital_twin/calibration.py`
- `digital_twin/repositories.py`
- `digital_twin/optimization.py`
- `digital_twin/connectivity.py`
- `digital_twin/feedback.py`
- `digital_twin/feedback_store.py`
- `digital_twin/synthetic_events.py`
- `services/digital_twin_service.py`
- `db/postgres_schema.sql`

Implemented features:

- Entity model: farm, zone, sensor, actuator, crop, soil state, event, decision, policy.
- Fog-summary ingestion contract and validation.
- Dynamic-ready `DigitalTwinEngine` with `step(...)`, `simulate(...)`, and `what_if(...)`.
- Pluggable process model interface.
- Default process models:
  - soil water balance
  - crop risk
  - equipment degradation
- Calibration profiles:
  - `CalibrationProfile`
  - `fit_soil_water_parameters(...)`
  - save/load helpers
- Repository abstraction:
  - SQLite default backend
  - PostgreSQL optional backend through `DB_BACKEND=postgres` and `DATABASE_URL`
- PostgreSQL/TimescaleDB target schema in `db/postgres_schema.sql`.
- Separate cloud digital twin service entrypoint: `services/digital_twin_service.py`.
- Human feedback label schema, persistent feedback store, and ML export path.
- Optimization foundation: `IrrigationOptimizer`.
- Twin connectivity foundation: `twin_state`, `twin_sync`, `twin_command` events.

### Dashboard / API

Main file: `tools/dashboard.py`

Implemented endpoints:

| Endpoint | Purpose |
|---|---|
| `/` | HTML dashboard |
| `/api/health` | Backend/Kafka/topic/auth health info |
| `/api/summary` | Event summary |
| `/api/events` | Latest cloud events |
| `/api/twin` | Digital twin zone state |
| `/api/feedback` | GET feedback labels, POST new feedback labels |
| `/api/feedback/export` | Export feedback labels as JSONL for ML |
| `/api/optimize/irrigation` | Basic irrigation optimization recommendations |

Dashboard security foundation:

- `DASHBOARD_TOKEN` works as fallback for all roles.
- Optional role tokens:
  - `DASHBOARD_READ_TOKEN`
  - `DASHBOARD_WRITE_TOKEN`
  - `DASHBOARD_ADMIN_TOKEN`
- Dashboard write/export audit log:
  - `DASHBOARD_AUDIT_PATH`

---

## Quick Start - Local Python

Use this for code work and tests.

```cmd
cd /d C:\Users\bella\Downloads\rihab\AgenticAiFog-integration-fog-final-merge
C:\Users\bella\Downloads\rihab\AgenticAiFog-main\_push_worktree\.venv\Scripts\python.exe -m unittest discover -s tests
```

If using your own venv:

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests
```

Optional integrations:

```cmd
pip install -r requirements-cloud.txt
pip install -r requirements-llm.txt
```

---

## Quick Start - Production-Like Docker Stack

Use this when testing Kafka/PostgreSQL/dashboard services.

1. Create `.env.production` from the example:

```cmd
cd /d C:\Users\bella\Downloads\rihab\AgenticAiFog-integration-fog-final-merge
copy .env.production.example .env.production
notepad .env.production
```

2. For local demo, these values are acceptable:

```text
DASHBOARD_TOKEN=AgenticFogDemo_2026
DB_BACKEND=postgres
DATABASE_URL=postgresql://agentic:agentic-demo-pass@postgres:5432/agentic_fog
```

3. In `docker-compose.production.yml`, make sure PostgreSQL uses the same password:

```yaml
POSTGRES_PASSWORD: agentic-demo-pass
```

4. Build and run:

```cmd
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
docker compose -f docker-compose.production.yml --env-file .env.production ps
docker compose -f docker-compose.production.yml --env-file .env.production logs -f digital-twin-service
```

5. Open:

```text
http://localhost:8050/?token=AgenticFogDemo_2026
http://localhost:8050/api/health?token=AgenticFogDemo_2026
http://localhost:8050/api/optimize/irrigation?token=AgenticFogDemo_2026
```

Expected after rebuild with `DB_BACKEND=postgres`:

```text
Dashboard backed by repository backend: postgres
```

If it still shows SQLite, rebuild/restart the dashboard container.

---

## Configuration

### Criticality

| Variable | Default | Purpose |
|---|---:|---|
| `CRITICALITY_MODE` | `local_first` | Local-first criticality mode |
| `CRITICALITY_ENABLE_REMOTE_FALLBACK` | `false` | Enables remote fallback only for ambiguity |
| `CRITICALITY_AMBIGUITY_MARGIN` | `1` | Ambiguity score margin |

### Cloud / Kafka / DB

| Variable | Default | Purpose |
|---|---:|---|
| `CLOUD_SYNC_MODE` | `local_queue` | `local_queue`, `http`, or `kafka` |
| `CLOUD_KAFKA_BOOTSTRAP` | unset | Kafka bootstrap server |
| `CLOUD_KAFKA_TOPIC` | `sensor-data` | Default summary topic |
| `CLOUD_KAFKA_DEAD_LETTER_TOPIC` | `fog-dead-letter` | Dead-letter topic |
| `DB_BACKEND` | `sqlite` | `sqlite` or `postgres` |
| `DATABASE_URL` | unset | PostgreSQL URL when `DB_BACKEND=postgres` |
| `FARM_ID` | `demo-farm` | Digital twin farm identity |
| `TWIN_SIMULATION_STEP_MINUTES` | `10` | Twin simulation step duration |

### Dashboard Security

| Variable | Default | Purpose |
|---|---:|---|
| `DASHBOARD_TOKEN` | unset | Fallback token for all dashboard roles |
| `DASHBOARD_READ_TOKEN` | unset | Optional read-only token |
| `DASHBOARD_WRITE_TOKEN` | unset | Optional feedback-write token |
| `DASHBOARD_ADMIN_TOKEN` | unset | Optional export/admin token |
| `DASHBOARD_AUDIT_PATH` | `logs/dashboard_audit.jsonl` | Dashboard write/export audit log |

### Actuation

| Variable | Default | Purpose |
|---|---:|---|
| `ACTUATOR_MODE` | `local_queue` | `local_queue`, `http`, `mqtt`, or `command` |
| `ACTUATOR_HTTP_ENDPOINT` | unset | HTTP actuator endpoint |
| `ACTUATOR_MQTT_HOST` | unset | MQTT broker host |
| `ACTUATOR_MQTT_PORT` | `1883` | MQTT port |
| `ACTUATOR_MQTT_TOPIC` | `fog/actuators` | MQTT actuator topic |
| `ACTUATOR_COMMAND_TEMPLATE` | unset | Local command template |

---

## Team Handover

### Zaaa - Agentic Context, Criticality, Documentation

Start here:

- `agents/context_manager_agent.py` - context layer owner file. Maintains rolling sensor history, averages, slopes, variance, derived agronomic features, and semantic context summaries used by decision making.
- `anomaly_detector.py` - multi-level anomaly detection. Combines physical/range checks, statistical behavior, and domain rules, then returns anomaly severity and explanation details.
- `context/multimodal_fusion.py` - placeholder interface for drone/satellite/weather-image metadata. It accepts source metadata and precomputed features now; real image ML can plug in later without changing `pipeline.py`.
- `agents/criticality_agent.py` - local-first criticality classifier. Scores the eight scenario labels and optionally calls a remote LLM only when configured for ambiguous cases.
- `pipeline.py` - full fog orchestration path. This is where trust, context, anomaly, multimodal, criticality, decision, enforcement, logs, and cloud summaries are connected.
- `tests/test_fog_components.py` - broad component tests for context, anomaly, multimodal, criticality, cloud events, twin, optimization, and dashboard foundations.
- `README.md` - teammate handover and architecture status. Keep it updated whenever contracts, owners, or implemented/remaining features change.

Already done:

- Context manager with history, averages, slopes, variance, derived features, and semantic summary.
- Multi-level anomaly detector integrated into `FogPipeline`.
- Per-decision explanation trace.
- Multimodal metadata placeholder.
- Local-first criticality classifier with optional remote fallback.
- Criticality tests for major scenarios.

Next tasks:

- Keep `CriticalityAgent.run(raw_readings, tinyml_output, context=None)` stable for Sonic/Sarra.
- Coordinate the real feature schema for ML and multimodal inputs.
- Keep README current after teammates add real hardware, models, or cloud deployment changes.

Do not rewrite:

- `CriticalityResult` contract.
- The explanation trace structure unless Lion and Limon agree.

### Lion - Decision, Safety Gates, Pipeline Stability

Start here:

- `pipeline.py` - integration point for the final decision. Check this file whenever a new ML, Kafka, edge, or twin feature changes the data flowing into the decision layer.
- `agents/decision_agent.py` - selects the decision path and final strategy: rule-based decision, cache reuse, LLM/cloud fallback, action, confidence, and explanation.
- `decision_cache.py` - persistent exact/similarity cache for reusing past decisions. Useful for fast local decisions and avoiding unnecessary remote calls.
- `action_handler.py` - policy enforcement point and action dispatch wrapper. Real actuator commands must pass through here.
- `metrics.py` - runtime counters/metrics for accepted, rejected, critical, local, cloud, and action outcomes.
- `tests/test_p0_stabilization.py` - stability and regression tests for core pipeline behavior, safety gates, rejection handling, and no-action behavior.

Already done:

- Final decision hierarchy: rule, cache, LLM, fallback/cloud.
- Similarity-aware decision cache.
- High-trust local action safety gates.
- `no_action` is a real no-op result.
- Decision confidence added.

Next tasks:

- Review new ML/Kafka/edge integrations so they do not bypass PEP/safety gates.
- Tune cache similarity threshold only after Sonic/Sarra provide real evaluation data.
- Extend safety tests when new actions or policies are added.

### Sonic + Sarra - ML Scenario Modeling

Start here:

- `models.py` - shared data contracts and enums. The eight criticality scenario labels live here and must stay stable unless every dependent test/schema/doc is updated.
- `agents/criticality_agent.py` - current deterministic local scenario classifier. Your trained model should plug in behind the existing `CriticalityAgent.run(raw_readings, tinyml_output, context=None)` contract.
- `digital_twin/synthetic_events.py` - rare/extreme event synthetic dataset generator and `RARE_EVENT_SCHEMA`. Use it for bootstrapping experiments, not as proof of real farm accuracy.
- `simulation/generator.py` - synthetic telemetry generator for fog pipeline experiments and scenario coverage.
- `federated/dataset_builder.py` - turns local fog/twin/feedback data into dataset rows for federated or distributed ML workflows.
- `tests/test_federated_dataset_builder.py` - regression tests for dataset row construction and export behavior.

Eight criticality scenarios currently used by the pipeline:

- `Normal` - no meaningful risk detected.
- `Water deficit` - low moisture, no rainfall, falling moisture trend, or TinyML irrigation signal.
- `Flooding` - high moisture, heavy rainfall, rising moisture trend, or stop-irrigation signal.
- `Fire or heat stress` - high temperature, frost/heat extremes, or high VPD.
- `Crop disease risk` - warm and high-humidity conditions.
- `Pest risk` - warm and moderately humid persistent conditions.
- `Soil degradation` - bad pH, low nutrients, or salinity risk.
- `Equipment failure` - physical anomalies, non-numeric values, impossible/out-of-range readings, or sensor failure evidence.

Available now:

- Deterministic local classifier for the eight scenarios.
- Synthetic rare/extreme event generator with documented schema.
- Feedback label export from dashboard: `/api/feedback/export`.
- Federated dataset foundation.

Next tasks:

- Build/provide a real labeled dataset for the eight criticality scenarios.
- Train and evaluate a scenario model.
- Report accuracy, precision, recall, F1, confusion matrix, and dangerous false positives/negatives.
- Export a model artifact or inference wrapper.
- Integrate behind the existing `CriticalityAgent.run(...)` contract.

Do not do this:

- Do not claim synthetic data performance is real farm accuracy.
- Do not rename scenario labels without updating `models.py`, tests, cloud schemas, and README.

### Limon - Kafka / Cloud Synchronization

Start here:

- `cloud_events.py` - versioned event envelope, event type constants, Kafka topic names, and routing rules for fog decisions, trust events, critical events, twin events, policy updates, model updates, and dead-letter events.
- `cloud_sync.py` - publisher layer. Supports local queue, HTTP, and Kafka modes, including retry/backoff and dead-letter fallback.
- `cloud_interface.py` - fog-to-cloud boundary used by the pipeline. It packages summaries, rejection events, and model/policy update hooks.
- `tools/cloud_storage_consumer.py` - Kafka consumer that stores cloud events through the repository backend. With `DB_BACKEND=postgres`, this writes to PostgreSQL.
- `tools/governance_consumer.py` - consumes `policy-updates` and `model-updates`, then applies them to local rule/model stores.
- `services/digital_twin_service.py` - separate cloud-side digital twin service. It consumes fog/twin events, updates twin state, and advances simulation steps.
- `docker-compose.production.yml` - production-like demo stack: Redpanda/Kafka, PostgreSQL, cloud consumers, digital twin service, governance consumer, dashboard, and backup.
- `db/postgres_schema.sql` - PostgreSQL/TimescaleDB target schema for cloud events, twin events, zone state, feedback labels, calibration profiles, policy versions, and model versions.

Important topics currently defined:

- `sensor-data` - default fog summary stream.
- `trust-events` - rejected/untrusted sensor events.
- `fog-decisions` - accepted fog decisions.
- `critical-events` - high-criticality events.
- `model-updates` - cloud-to-fog model update metadata.
- `policy-updates` - cloud-to-fog policy/rule update metadata.
- `fog-dead-letter` - events that failed normal delivery.
- `twin-state` - cloud twin state publication.
- `twin-sync` - inter-twin synchronization events.
- `twin-command` - commands between twin services or governance systems.

Already done:

- Versioned cloud event envelope.
- Kafka/local topic routing.
- Retry/backoff and dead-letter handling.
- Local Redpanda stack.
- PostgreSQL target schema.
- Repository-backed cloud storage path.
- Governance consumer for `policy_update` and `model_update`.

Next tasks:

- Verify final Kafka topic names with the team.
- Decide production broker auth/TLS/retention/partitioning strategy.
- Decide if Redpanda stays for demo only or if the team uses managed Kafka/Confluent/MSK/Event Hubs.
- Add real monitoring/alerts for Kafka consumers if deployed beyond local demo.

### 3otri - Edge / TinyML / Hardware / Actuators

Start here:

- `agents/data_validation_agent.py` - validates required sensor fields, sensor identity, field types, and supported payload structure before data enters the fog pipeline.
- `actuator_adapters.py` - actuator backend implementations. Local queue works offline; HTTP, MQTT, and command adapters are ready for real gateway/hardware integration.
- `action_handler.py` - enforcement and dispatch layer. It checks action permissions and sends allowed commands through the selected actuator adapter.
- `simulation/telemetry_schema.py` - reference telemetry schema for simulated/edge payloads. Use this when aligning real gateway JSON with the fog pipeline.
- `config.py` - central runtime configuration: sensor rules, trust thresholds, cloud mode, actuator mode, paths, and environment-variable based settings.

Important edge payload fields:

- Required agricultural fields today: `soil_moisture`, `temperature`, `humidity`, `rainfall`, `ph`, `nitrogen`, `phosphorus`, `potassium`.
- Supported optional/extension fields include pressure and additional IoT measurements when validation/config is extended.
- TinyML output should provide an action-like recommendation such as `irrigate`, `stop_irrigation`, or `no_action`, plus confidence if available.

Available now:

- Sensor message schema with required and optional fields.
- TinyML output validation contract.
- Actuator adapters for local queue, HTTP, MQTT, and command mode.
- Local queue fallback so the pipeline runs without hardware.

Next tasks:

- Define the real field gateway JSON payload.
- Implement or emulate TinyML inference on edge hardware.
- Provide real actuator backend: MQTT, HTTP gateway, GPIO/relay driver, PLC, or command script.
- Add actuator confirmation/feedback telemetry.
- Ensure emergency edge actions do not depend on cloud availability.

### Digital Twin Owner - TBD

Start here:

- `digital_twin/entities.py` - core twin domain model: farm, zone, sensor, actuator, crop, soil state, event, decision, and policy.
- `digital_twin/contracts.py` - fog-summary ingestion contract. This normalizes pipeline summaries before they update cloud-side twin state.
- `digital_twin/simulator.py` - `DigitalTwinEngine`. Applies fog summaries, updates zone state, runs dynamic simulation steps, exposes dashboard-ready state, and supports what-if scenarios.
- `digital_twin/process_models.py` - pluggable process-model interface and default models for soil water balance, crop risk, and equipment degradation.
- `digital_twin/calibration.py` - calibration profiles and fitting helpers. Use this when real farm measurements become available.
- `digital_twin/repositories.py` - storage abstraction. Selects SQLite for local mode or PostgreSQL when `DB_BACKEND=postgres`.
- `digital_twin/optimization.py` - optimization foundation, currently irrigation scheduling/recommendation across zones.
- `digital_twin/connectivity.py` - inter-twin and intra-twin event contracts for twin state, synchronization, and commands.
- `digital_twin/synthetic_events.py` - synthetic rare/extreme event generation for ML experiments and stress testing.
- `digital_twin/feedback.py` - human feedback, reviewed label, policy update, and model update schemas.
- `digital_twin/feedback_store.py` - feedback persistence/export helper used by dashboard and ML handoff.
- `services/digital_twin_service.py` - runnable cloud digital twin service entrypoint used by Docker Compose.
- `tools/dashboard.py` - dashboard/API for health, event summaries, twin state, feedback labels, feedback export, and optimization output.
- `db/postgres_schema.sql` - production target database schema for twin/cloud persistence.

Already done:

- Dynamic-ready twin engine.
- Pluggable process models.
- Calibration profile/fitting hooks.
- Repository abstraction for SQLite/PostgreSQL.
- Separate service entrypoint.
- Dashboard/API health, twin state, feedback, export, and optimization endpoint.
- Twin connectivity event contracts.

Next tasks needing real input:

- Assign the actual digital twin owner.
- Collect real calibration data.
- Replace default deterministic process models with calibrated agronomic/hydraulic/ML models.
- Decide if production remains this Python service or later moves to a managed digital twin platform.
- Improve the dashboard UI if a production-facing interface is required.
## Real Data Needed For Calibration

The code supports calibration, but the project does not yet have real farm data. Minimum useful rows look like:

```csv
farm_id,zone_id,timestamp_before,timestamp_after,before_moisture,after_moisture,minutes,rainfall,irrigated,temperature,humidity,soil_type,crop_type,growth_stage
farm-1,zone-1,2026-01-01T08:00:00Z,2026-01-01T09:00:00Z,20,31,60,0,true,30,45,loam,tomato,vegetative
```

Minimum required columns for current fitting helper:

- `before_moisture`
- `after_moisture`
- `minutes`
- `rainfall`
- `irrigated`
- `temperature`
- `humidity`

Better additional columns:

- irrigation duration and flow rate
- soil type
- crop type and growth stage
- pH, salinity, N/P/K
- disease/pest observations
- equipment maintenance/failure logs

---

## Remaining External Decisions / Work

These cannot be honestly completed by code alone:

| Item | Status | Needs |
|---|---|---|
| Real farm calibration data | Not done | Field measurements from team/farm/simulation owner |
| Real trained scenario model | Not done | Sonic/Sarra dataset and model work |
| Real hardware feedback loop | Not done | 3otri hardware/edge integration |
| Real production hosting | Not done | Team/supervisor platform decision |
| Real TLS/IAM/RBAC/security infrastructure | Partial foundation only | Deployment/cloud/security owner |
| Real optimization model | Foundation only | Domain/ML constraints and objectives |
| Real inter-twin deployment | Event contracts only | Multiple twin instances or cloud deployment |

---

## Project Structure

```text
agents/                         Fog trust/context/decision agents
context/multimodal_fusion.py     Drone/satellite metadata interface placeholder
pipeline.py                      Main fog pipeline orchestration
anomaly_detector.py              Multi-level anomaly detector
action_handler.py                PEP and action routing
actuator_adapters.py             Local/HTTP/MQTT/command actuator adapters
cloud_events.py                  Event schemas and Kafka topic routing
cloud_sync.py                    Local/HTTP/Kafka publishers, retry, dead-letter
cloud_interface.py               Fog-to-cloud boundary
cloud_storage.py                 SQLite cloud/twin stores for local mode
support_services.py              Resource/connectivity/rules/security helpers
decision_cache.py                Persistent exact/similarity decision cache

digital_twin/                    Twin entities, contracts, simulation, repositories,
                                 calibration, optimization, connectivity, feedback
services/digital_twin_service.py Separate cloud twin service entrypoint
db/postgres_schema.sql           PostgreSQL/TimescaleDB target schema

tools/cloud_storage_consumer.py  Kafka-to-repository cloud event consumer
tools/digital_twin_consumer.py   Legacy/simple Kafka-to-SQLite twin consumer
tools/governance_consumer.py     Policy/model update consumer
tools/dashboard.py               Repository-backed dashboard/API
tools/backup_sqlite.py           SQLite backup utility
tools/retention.py               SQLite retention pruning utility

docker-compose.yml               Local Redpanda-only stack
docker-compose.production.yml    Production-like Redpanda/Postgres/service stack
DEPLOYMENT.md                    Runtime/deployment runbook

tests/                           Regression tests
```

---

## Tests

Run before pushing:

```cmd
cd /d C:\Users\bella\Downloads\rihab\AgenticAiFog-integration-fog-final-merge
C:\Users\bella\Downloads\rihab\AgenticAiFog-main\_push_worktree\.venv\Scripts\python.exe -m unittest discover -s tests
```

Current verified result:

```text
Ran 64 tests
OK
```

Tests cover:

- trust/context/anomaly/criticality behavior
- local-first criticality scenarios
- pipeline smoke runs
- explanation trace and multimodal placeholder
- decision cache and safety gates
- cloud events, topic routing, retry/dead-letter
- local storage and digital twin persistence
- dynamic twin simulation, calibration, what-if, optimization
- feedback export and governance updates
- repository backend selection
- dashboard health API foundation
- twin connectivity event contracts

---

## Important Rules For Teammates

- Keep local/offline mode working. Do not make tests require Kafka, Docker, PostgreSQL, Groq, or hardware.
- Keep `CriticalityAgent.run(raw_readings, tinyml_output, context=None)` stable.
- Keep fog summaries compact by default; do not upload raw high-frequency streams unless explicitly required.
- Do not bypass `ActionHandler` / PEP for real actuator commands.
- Do not claim deterministic/synthetic results are real farm accuracy.
- Do not commit `.env.production` or real secrets.

---

## Authors

- Zaaa 
- Lion
- Sonic
- Sarra
- Limon
- 3otri

