# Kafka / Redpanda Integration Fixes

**Branch**: `fix/kafka-working`
**Date**: 2026-08-13

---

## What was broken

### 1. Redpanda Console could not connect to the broker

The dev `docker-compose.yml` advertised `PLAINTEXT://localhost:9092` as the
broker address for all clients. This works for programs running directly on
the host (port-mapped `localhost:9092`), but silently breaks Docker-internal
services:

1. The Console container bootstraps via `redpanda:9092` (Docker DNS).
2. Redpanda responds with cluster metadata whose advertised address is
   `localhost:9092`.
3. The Console then tries to connect to `localhost:9092` — which inside its
   own container resolves to itself, not Redpanda.

Result: the Console started, showed no brokers, and displayed no topics or
messages.

**Fix**: Dual-listener configuration in dev compose:

```
INTERNAL://0.0.0.0:29092  advertised as  redpanda:29092   (Docker services)
EXTERNAL://0.0.0.0:9092   advertised as  localhost:9092   (host clients)
```

The Console now bootstraps from `redpanda:29092`. Python clients on the host
continue to use `localhost:9092`.

---

### 2. KafkaPublisher opened a new TCP connection for every message

`cloud_sync.KafkaPublisher.publish()` constructed a brand-new `KafkaProducer`,
flushed it, and closed it on every single call. Each call paid:
- A full TCP handshake
- Kafka protocol handshake + metadata fetch (~100–300 ms)
- Connection teardown

For a pipeline run of 50 readings that each publish 3–4 events, this is
150–200 unnecessary connection round-trips.

**Fix**: `KafkaPublisher` lazily creates one `KafkaProducer` per instance and
reuses it for every `publish()` call. Configuration improvements:

| Parameter   | Before | After                          |
|-------------|--------|--------------------------------|
| `acks`      | `1`    | `"all"` (at-least-once guarantee) |
| `retries`   | `0`    | `3`                            |
| `linger_ms` | `0`    | `5` (small batch window)       |

A `close()` method is added for explicit teardown.

---

### 3. `build_cloud_publisher()` used stale import-time constants

`config.py` reads environment variables once at import time and binds them to
module-level names (`CLOUD_SYNC_MODE`, `CLOUD_KAFKA_BOOTSTRAP`). Those names
are bound before `main()` runs.

When `main.py --kafka` set `os.environ["CLOUD_SYNC_MODE"] = "kafka"` after
`config` was already imported, `build_cloud_publisher()` still read the
original `"local_queue"` constant, and every message went to the local file
queue instead of Kafka.

**Fix**: `build_cloud_publisher()` now calls `os.getenv()` at invocation time,
falling back to the module-level constant only if the env var is absent.
Runtime overrides from `--kafka` (or any other caller) take effect immediately.

---

### 4. `auto_create_topics_enabled` missing in dev compose

The production `docker-compose.production.yml` had
`redpanda.auto_create_topics_enabled=true` but the dev compose did not.
Publishing to a topic that did not yet exist raised an
`UnknownTopicOrPartitionError` (or the message was silently dropped,
depending on Kafka client settings).

**Fix**: Added `--set redpanda.auto_create_topics_enabled=true` to the dev
Redpanda command.

---

### 5. No healthcheck on Redpanda in dev compose

The Console started immediately after Docker created the Redpanda container,
before the broker had finished initialising. This caused repeated
"connection refused" errors and misleading log noise at startup.

**Fix**: Added a `healthcheck` (`rpk cluster health`) to the Redpanda service
and changed the Console's `depends_on` to `condition: service_healthy`.

---

### 6. `kafka-python` missing from base `requirements.txt`

The package was only listed in `requirements-cloud.txt`. Running any code path
that touched Kafka — producers, consumers, `build_cloud_publisher()` — raised
`ModuleNotFoundError: No module named 'kafka'` unless the optional cloud
dependencies were explicitly installed first.

**Fix**: `kafka-python>=2.0.2` added to the base `requirements.txt`.

---

## What was added

### `tools/setup_topics.py` — topic initialisation script

Creates all ten Kafka topics required by the fog pipeline with calibrated
partition counts. Idempotent: already-existing topics are reported as
`already_exists`, not errors.

```bash
python -m tools.setup_topics                          # localhost:9092
python -m tools.setup_topics --bootstrap host:9092   # custom broker
python -m tools.setup_topics --list                  # show existing topics
python -m tools.setup_topics --dry-run               # preview without creating
```

Topics created:

| Topic             | Partitions | Purpose                            |
|-------------------|:----------:|------------------------------------|
| `sensor-data`     | 3          | Fog summaries and telemetry        |
| `fog-decisions`   | 2          | Per-reading agent decisions        |
| `trust-events`    | 1          | Trust score changes / rejections   |
| `critical-events` | 1          | High-severity escalations          |
| `model-updates`   | 1          | TinyML model distribution          |
| `policy-updates`  | 1          | Rule / policy updates from cloud   |
| `fog-dead-letter` | 1          | Failed publish retries             |
| `twin-state`      | 1          | Digital twin current state         |
| `twin-sync`       | 1          | Twin synchronisation events        |
| `twin-command`    | 1          | Commands sent to the twin          |

---

### `main.py --kafka` flag

Enables Kafka publishing for a complete pipeline run without setting
environment variables manually:

```bash
python main.py --offline --limit 20 --kafka
python main.py --offline --limit 20 --kafka --kafka-bootstrap localhost:9092
```

The flag sets `CLOUD_SYNC_MODE=kafka` and `CLOUD_KAFKA_BOOTSTRAP` before any
pipeline objects are constructed, so `build_cloud_publisher()` picks them up.

---

## Quick-start

```bash
# 1. Start Redpanda + Console (health-checked, dual-listener)
docker compose up -d

# 2. Create all pipeline topics
python -m tools.setup_topics

# 3. Run the pipeline with Kafka publishing
python main.py --offline --limit 20 --kafka

# 4. Verify: topics should have messages
python -m tools.setup_topics --list

# 5. Browse topics and messages
#    Open http://localhost:8080 in a browser (Redpanda Console)
```

---

## Files changed

| File                      | Change                                    |
|---------------------------|-------------------------------------------|
| `docker-compose.yml`      | Dual listener, healthcheck, auto-create   |
| `cloud_sync.py`           | Long-lived producer, live env reads       |
| `main.py`                 | `--kafka` / `--kafka-bootstrap` flags     |
| `requirements.txt`        | Added `kafka-python>=2.0.2`               |
| `tools/setup_topics.py`   | New — topic admin script                  |
