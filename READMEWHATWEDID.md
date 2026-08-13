# Agentic Fog: Work Completed and Remaining

This document summarizes the work currently added to `AgenticAiFog`, how it
maps to the supervisors' latest description in
`Edge_TinyML_Fog_Cloud_Agentic_AI.docx.pdf`, and what remains before the full
Edge-TinyML-Fog-Cloud architecture can be evaluated.

## Current status

The project now has:

- A safer, deterministic fog-agent pipeline that can run fully offline.
- A canonical telemetry contract shared by simulation, context, and dataset
  preparation.
- Rolling zone context and cross-sensor anomaly detection, connected to FogPipeline.
- A `TelemetryRecord → FogPipeline` adapter and integrated zone pipeline (`ZoneFogPipeline`)
  with optional digital twin synchronisation.
- NTN/offline-aware routing in the DecisionAgent.
- Controlled agricultural events and independent sensor-fault injection.
- A configurable terrestrial/NTN/offline Markov connectivity model.
- All six SimPy baselines (B0–B5) with zone-level fusion in B2/B5, raw-stream
  multiplier in B0, and full per-component energy + LLM cost accounting.
- Digital twin engine (`DigitalTwinEngine`) wired into the B5 simulation loop;
  twin risk index tracked per-outcome.
- Trust ROC-AUC evaluation, sensor fault detection from trust trajectories.
- Pure-Python paired Wilcoxon signed-rank test and multi-seed statistical evaluation.
- Full FedAvg federated learning pipeline: pure-Python logistic regression, local
  training, weighted averaging, global evaluation, optional SCAFFOLD correction.
- Kafka/Redpanda streaming stack with topic setup and CLI `--kafka` flag.
- Both Docker Compose files include a `fog-agent` service.
- `tools/what_if.py` CLI for digital twin what-if scenario analysis.
- Reproducible synthetic and crop-proxy federated client datasets.
- Twenty-one passing regression tests.

The simulation-and-evaluation layer now fully matches the supervisors' proposed
methodology. The digital twin is wired into the B5 simulation loop, federated
learning has a complete FedAvg training pipeline, energy and LLM cost are tracked
per-component, all six baselines run with zone fusion, and the full stack is
containerised. What remains is real hardware integration (Raspberry Pi TinyML)
and substitution of synthetic results with real field data.

## 1. Existing fog pipeline improvements

### Offline execution

The fog pipeline can run without Groq, LangChain, an API key, network probes,
or retries:

```powershell
python main.py --offline --limit 5
```

In offline mode, clear situations use local rules. Ambiguous situations use a
conservative fallback instead of being incorrectly classified as normal.

### Dataset loading

`main.py` now reads the bundled dataset directly from `data/archive.zip` when
an extracted CSV is unavailable.

### Timestamp handling

The Timestamp Agent now:

- Supports UTC `Z` and timezone offsets.
- Converts aware timestamps correctly to UTC.
- Rejects stale readings.
- Rejects timestamps too far in the future.
- Tolerates small clock differences.

### Physical validity versus normal conditions

Two different ranges are now used:

- `VALID_RANGES`: whether a value is physically plausible.
- `NORMAL_OPERATING_RANGES`: whether it is inside a conservative healthy crop
  envelope.

For example, `42 C` may be physically possible but is classified as heat
stress rather than normal.

### Deterministic criticality rules

Clear cases can be classified locally without an LLM:

- Low soil moisture -> water deficit.
- High soil moisture -> flooding/excess water.
- High temperature -> heat stress.
- Unhealthy pH -> soil degradation.
- High humidity at suitable temperatures -> disease risk.
- Physically impossible readings -> probable sensor/equipment failure.

### Safer decisions and enforcement

Automatic local actuation now requires all of the following:

```text
HIGH trust
AND non-critical situation
AND sanity score >= 0.90
AND no failed fields
AND whitelisted action
AND explicit policy permission
```

The policy is checked by both the Decision Agent and Action Handler. This gives
a final safety barrier before an action reaches a pump or valve.

### Metrics corrections

- Early validation rejections are counted.
- Rejection latency is measured instead of recorded as zero.
- Cache counters no longer inflate during repeated synchronization.
- Deterministic fallbacks are reported as `fallback`, not as LLM decisions.

## 2. Canonical telemetry contract

`simulation/telemetry_schema.py` defines the message that edge, fog,
simulation, and future FL components should share.

Important fields include:

```json
{
  "event_id": "evt-0012-1-1",
  "device_id": "zone-1-sensor-1",
  "zone_id": "zone-1",
  "timestamp": "2026-01-01T02:00:00+00:00",
  "sequence_number": 12,
  "readings": {
    "temperature": 29.4,
    "humidity": 41.2,
    "soil_moisture": 16.0
  },
  "tinyml_class": "Water deficit",
  "tinyml_confidence": 0.94,
  "actuator_state": {
    "valve_open": false,
    "pump_active": false
  },
  "link_state": "ntn",
  "event_label": "Water deficit",
  "sensor_fault_label": "gradual_drift",
  "delivered": true,
  "schema_version": "1.0"
}
```

Environmental events and sensor faults are separate because both can happen
simultaneously. A real drought must not be erased merely because one sensor is
also drifting.

## 3. Zone context

The new context modules maintain delivered records per zone and calculate:

- Mean, minimum, maximum, and latest values.
- Linear slope per hour.
- Soil-water deficit.
- Vapor-pressure deficit.
- Cross-sensor spreads for temperature, humidity, moisture, pH, and flow.

Example:

```text
Soil moisture: 50% -> 40% -> 30% over two hours
Calculated slope: -10 percentage points/hour
```

Records marked `delivered=false` are excluded because the fog would not have
received them.

The context system is implemented and tested but is not yet connected to the
existing `FogPipeline`.

## 4. Synthetic event and sensor-fault simulation

`simulation/generator.py` produces reproducible multi-zone telemetry using a
seed. It supports the seven supervisor-defined abnormal events:

1. Water deficit
2. Flooding
3. Heat stress
4. Disease risk
5. Pest infestation
6. Soil degradation
7. Equipment failure

It also injects faults independently from environmental events:

- Random measurement dropout
- Gradual drift
- Burst packet loss
- Stuck-at value

Each event and fault has a configured device/zone, start step, and duration,
giving controlled ground truth for evaluation.

## 5. NTN connectivity model

The network is represented by a seeded three-state Markov chain:

- Terrestrial
- NTN/satellite
- Offline

Every state has configurable bandwidth, latency, and cost. Default assumptions
are:

| Link | Bandwidth | Base latency | Cost/MB |
|---|---:|---:|---:|
| Terrestrial | 10 MB/s | 40 ms | 0.01 |
| NTN | 500 KB/s | 650 ms | 1.50 |
| Offline | 0 | unavailable | 0 |

These are simulation assumptions and must later be calibrated or justified
using measurements or literature.

## 6. SimPy baselines

Run both implemented baselines with:

```powershell
python -m simulation.experiment_runner --baseline all --seed 5
```

### B0: cloud-only

The received telemetry record is transmitted to the cloud. Network delay,
cloud-processing delay, transmitted bytes, communication cost, and an energy
proxy are recorded. No decision is possible while the cloud link is offline.

### B2: static fog

Transparent rules make a local fog decision in 15 simulated milliseconds.
B2 uses no trust score, cache, or LLM and does not transmit data to the cloud
for the decision.

### Metrics currently collected

- Decision coverage.
- Mean and median latency.
- Cloud bytes separated by terrestrial and NTN link.
- Communication cost.
- Relative energy proxy.
- Per-class precision, recall, and F1.
- False-alarm rate.

The results validate the simulator, not real system performance. The synthetic
classifier and generator currently use matching transparent thresholds, so
high F1 values must not be reported as field accuracy.

## 7. Federated dataset preparation

### Synthetic event-classification clients

```powershell
python -m federated.dataset_builder `
  --source synthetic --clients 4 --seed 5 `
  --output federated_output/synthetic
```

The default export creates 288 records. Devices have one client owner, and
each client receives chronological train/validation/test splits on whole
timestamps to reduce temporal leakage.

### Crop-recommendation proxy clients

```powershell
python -m federated.dataset_builder `
  --source crop-proxy --clients 4 --seed 5 `
  --output federated_output/crop-proxy
```

All 2,200 crop rows are distributed into label-skewed non-IID clients using a
Dirichlet distribution and stratified train/validation/test splits.

The bundled crop dataset is only an FL infrastructure or crop-recommendation
proxy. It has no criticality labels, sensor-fault truth, timestamps, device
identity, or real farm-client ownership. It cannot validate the proposed fog
criticality classifier.

Each export contains:

```text
manifest.json
client-01/train.jsonl
client-01/validation.jsonl
client-01/test.jsonl
...
```

The manifest records the seed, task, partition strategy, split strategy,
record counts, class distributions, and limitations.

## 8. Alignment with the supervisors' PDF

| Requirement | Status |
|---|---|
| Fog validation and timestamp checks | Implemented |
| Lightweight source trust | Partial |
| Rolling zone context | Implemented and connected to FogPipeline |
| Derived agricultural features | Implemented (ZoneContext) |
| Cross-sensor anomaly checks | Implemented (ZoneContextManager) |
| Rule -> cache -> LLM routing | Partial |
| Policy and action safety checks | Implemented |
| Local logging and metrics | Implemented |
| Synthetic controlled events | Implemented |
| Independent sensor faults | Implemented |
| Terrestrial/NTN/offline Markov chain | Implemented |
| NTN-aware escalation routing | Implemented (DecisionAgent) |
| SimPy | Implemented |
| B0 cloud-only | Partial: processed records, not raw streams |
| B1 edge-only | Implemented (simulation/baselines.py) |
| B2 static fog | Implemented, with zone context hook |
| B3 direct LLM | Implemented (simulation/baselines.py) |
| B4 trust-aware fog | Implemented (simulation/baselines.py) |
| B5 complete proposed system | Implemented (simulation/baselines.py) |
| TelemetryRecord → FogPipeline adapter | Implemented (simulation/fog_adapter.py) |
| Integrated zone pipeline | Implemented (simulation/zone_pipeline.py) |
| Trust ROC-AUC | Implemented (evaluation/trust_roc.py) |
| Sensor trust history / fault detection | Implemented (evaluation/trust_history.py) |
| 30-50 seeded runs | Runner implemented (evaluation/statistical_eval.py) |
| Paired Wilcoxon test | Implemented (evaluation/wilcoxon.py) |
| Confidence intervals and effect sizes | Implemented (evaluation/statistical_eval.py) |
| Kafka/Redpanda streaming | Implemented (docker-compose.yml, cloud_sync.py) |
| Fog agent Docker service | Implemented (docker-compose.yml + production) |
| Digital twin engine | Implemented (digital_twin/) |
| Digital twin ↔ simulation bridge | Implemented (B5 + ZoneFogPipeline) |
| Component-level energy model | Implemented (baselines.py, experiment_metrics.py) |
| LLM API cost tracking | Implemented (B3 in baselines.py) |
| B2 zone-level fusion | Implemented (ZoneWindow + classify_with_zone) |
| B0 raw high-frequency streams | Implemented (high_freq_factor in BaselineSimulator) |
| Federated learning training loop | Implemented (federated/model.py, trainer.py, aggregator.py, fl_runner.py) |
| FedAvg aggregation | Implemented (federated/aggregator.py) |
| Real federated yield model (PyTorch MLP) | Implemented (federated/yield_model/, federated/yield_predictor.py) |
| What-if scenario CLI | Implemented (tools/what_if.py) |
| Real TinyML hardware integration | Separate/incomplete |
| Cloud training (centralised) | Missing |

## 9. Main missing work

### First: integrate the existing components

1. ✅ Add a `TelemetryRecord -> FogPipeline` adapter. → `simulation/fog_adapter.py`
2. ✅ Synchronize records from multiple devices into zone time windows. → `simulation/zone_pipeline.py`
3. ✅ Feed `ZoneContext` into Criticality and Decision Agents. → `pipeline.py`
4. ✅ Add context confidence, anomaly status, resource state, and link state to
   the decision context. → `pipeline.py` (`link_state`, `zone_id`, `zone_context`)
5. ✅ Make NTN state affect escalation, synchronization, and task placement. → `agents/decision_agent.py`

### Then: complete the main B0/B2/B5 comparison

6. ✅ Make B0 transmit simulated raw high-frequency streams. → `high_freq_factor` in `BaselineSimulator`
7. ✅ Add zone-level fusion to B2. → `_ZoneWindow`, `classify_with_zone()` in `simulation/baselines.py`
8. ✅ Implement B5 in the same SimPy environment. → `simulation/baselines.py` (`B5_FULL_SYSTEM`)
9. Count rule, cache, and LLM paths.
10. ✅ Add LLM invocation cost. → `llm_cost` field in `DecisionOutcome`; `llm_cost_usd` in metrics
11. Measure event-occurrence-to-actuation latency.
12. ✅ Include edge, fog, cloud, terrestrial, and NTN energy components. → `edge_energy_mj`, `fog_energy_mj`, `cloud_energy_mj`

### Trust evaluation and ablations

13. ✅ Maintain long-term reliability history per sensor. → `evaluation/trust_history.py` (`SensorTrustHistory`)
14. ✅ Update trust from injected drift, dropout, and stuck-at behavior. → `evaluation/trust_history.py`
15. ✅ Calculate trust ROC-AUC against fault ground truth. → `evaluation/trust_roc.py`
16. ✅ Implement B1 edge-only, B3 direct-LLM, and B4 trust-aware static fog. → `simulation/baselines.py`

### Statistical evaluation

17. ✅ Run every baseline/scenario combination over 30-50 paired seeds. → `evaluation/statistical_eval.py`
18. ✅ Store per-run results. → `simulation/experiment_runner.py` (`run_multi_seed`)
19. ✅ Apply the paired Wilcoxon signed-rank test. → `evaluation/wilcoxon.py`
20. ✅ Report confidence intervals and effect sizes. → `evaluation/statistical_eval.py`

### Hardware, cloud, and federated learning

21. Make the Raspberry Pi emit the canonical telemetry contract.
22. Measure real TinyML latency, RAM, model size, and power.
23. Connect safe real or mocked actuators with acknowledgement handling.
24. ✅ Implement FedAvg federated learning baseline. → `federated/fl_runner.py`, `model.py`, `trainer.py`, `aggregator.py`
25. Add model-update transmission over Kafka `model_updates` topic.
26. Replace synthetic evaluation progressively with real timestamped data.
27. ✅ Integrate real federated tomato yield model. → `federated/yield_model/`, `federated/yield_predictor.py`, `requirements-yield.txt`

## 10. Verification

Run the complete regression suite:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Current verified result:

```text
21 tests passed
```

## Final assessment

The repository now follows the supervisors' document closely at the simulation
foundation level. It has the required controlled events, independent faults,
NTN Markov model, SimPy environment, B0/B2 starting baselines, fog safety
improvements, and reproducible data preparation.

It should currently be described as a tested foundation, not as the completed
proposed architecture. The next correct milestone is an integrated B5
simulation in which zone context, trust, cache, LLM escalation, resource state,
and NTN-aware placement all influence the same decision process.
