# Deployment And Operations Runbook

This project now includes a real runnable local Kafka/cloud-storage/dashboard/digital-twin stack for development and demo. It is not a production cloud deployment. Production still needs team decisions for hosting, security, retention policy, dashboard ownership, monitoring, and a real farm-wide digital twin simulation.

## What This Stack Provides

- Kafka-compatible broker for local integration through Redpanda.
- Real event publishing from the fog pipeline when `CLOUD_SYNC_MODE=kafka` is enabled.
- SQLite cloud event storage through `tools/cloud_storage_consumer.py`.
- SQLite digital twin state storage through `tools/digital_twin_consumer.py`.
- Browser dashboard through `tools/dashboard.py`.
- Basic dashboard token authentication through `DASHBOARD_TOKEN`.
- SQLite backup utility through `tools/backup_sqlite.py`.
- Retention pruning utility through `tools/retention.py`.
- Docker Compose files for local demo and production-like packaging.

## Local Demo Stack

Use this when developing on a laptop.

```cmd
cd /d C:\Users\bella\Downloads\rihab\AgenticAiFog-integration-fog-final-merge
copy .env.cloud.example .env.cloud
docker compose --env-file .env.cloud up -d
```

Then run the fog pipeline with cloud sync enabled from the same environment. The Redpanda Console is available from the compose file, and the dashboard can be started with:

```cmd
python -m tools.dashboard --host 127.0.0.1 --port 8050
```

Open:

```text
http://127.0.0.1:8050
```

## Production-Like Local Stack

Use this to run the full packaged stack with containers.

```cmd
cd /d C:\Users\bella\Downloads\rihab\AgenticAiFog-integration-fog-final-merge
copy .env.production.example .env.production
notepad .env.production
```

Before starting, change at least:

```text
DASHBOARD_TOKEN=change-this-dashboard-token
```

Start the stack:

```cmd
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
```

Check logs:

```cmd
docker compose -f docker-compose.production.yml --env-file .env.production logs -f
```

Dashboard:

```text
http://localhost:8050/?token=<your-dashboard-token>
```

The dashboard also accepts API calls with:

```text
Authorization: Bearer <your-dashboard-token>
```

## Consumers

The two consumers are separate processes because they represent two different cloud services.

- `tools/cloud_storage_consumer.py`: reads Kafka events and persists event history into `CLOUD_DB_PATH`.
- `tools/digital_twin_consumer.py`: reads Kafka events and updates zone-level twin state in `DIGITAL_TWIN_DB_PATH`.

The current digital twin is an event-driven state mirror. It is not yet a full simulator of crop growth, hydraulics, machinery, spatial field conditions, or farm-wide dynamics.

## Backup

Run a manual backup:

```cmd
docker compose -f docker-compose.production.yml --env-file .env.production run --rm backup
```

Or outside Docker:

```cmd
python -m tools.backup_sqlite --cloud-db state\cloud_events.db --twin-db state\digital_twin.db --backup-dir backups
```

## Retention

Run retention pruning manually:

```cmd
python -m tools.retention --days 90 --cloud-db state\cloud_events.db --twin-db state\digital_twin.db
```

In production, retention should be scheduled by the deployment platform, for example cron, Kubernetes CronJob, Windows Task Scheduler, or a managed cloud scheduler.

## Security Notes

Implemented now:

- Dashboard bearer/query token gate through `DASHBOARD_TOKEN`.
- Fog-side HMAC message signing and tamper-evident audit chain in `support_services.py`.
- Policy/action whitelist checks before actuation.

Still required before a real production deployment:

- TLS termination through a reverse proxy or platform load balancer.
- Secret manager for Kafka credentials, HMAC keys, dashboard token, and model-update credentials.
- Per-user roles for dashboards and operations.
- Broker authentication and authorization.
- Certificate rotation and key rotation process.
- Network firewall rules so Kafka and SQLite volumes are not exposed publicly.
- Centralized logs/metrics/alerts.

## Production Decisions Still Needed

The team still needs to decide:

- Hosting target: local farm server, VM, Kubernetes, cloud VM, or managed cloud services.
- Kafka target: Redpanda, Apache Kafka, Confluent Cloud, AWS MSK, Azure Event Hubs, or another broker.
- Long-term storage: SQLite is only local/dev. Production likely needs PostgreSQL, TimescaleDB, object storage, or a managed analytics store.
- Dashboard target: current dashboard is basic. Production may need Grafana, Streamlit, custom web UI, or integration with a supervisor dashboard.
- Digital twin scope: current implementation mirrors latest zone state. A real digital twin needs data model, spatial zones, simulation logic, calibration, and owner assignment.
- Retention policy: how long to keep raw events, summaries, audit logs, model updates, and twin state.
- Backup and restore policy: schedule, destination, encryption, and restore testing.

## Verification

Run before sharing a branch:

```cmd
python -m py_compile pipeline.py cloud_storage.py cloud_sync.py cloud_interface.py tools\dashboard.py tools\backup_sqlite.py tools\retention.py
python -m unittest discover -s tests
```

## PostgreSQL Production Target

Production-like compose now includes PostgreSQL and initializes `db/postgres_schema.sql`.

1. Copy and edit the production env file:

```cmd
copy .env.production.example .env.production
notepad .env.production
```

2. Change at least:

```text
DASHBOARD_TOKEN=<strong-token>
DATABASE_URL=postgresql://agentic:change-me@postgres:5432/agentic_fog
```

3. Start the stack:

```cmd
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
```

4. Check services:

```cmd
docker compose -f docker-compose.production.yml --env-file .env.production ps
docker compose -f docker-compose.production.yml --env-file .env.production logs -f digital-twin-service
```

The production target is now:

```text
Fog nodes -> Kafka/Redpanda -> separate digital-twin-service -> PostgreSQL/TimescaleDB schema -> dashboard/API
```

SQLite remains the local fallback. PostgreSQL requires Docker or a real database server.

## Dashboard Backend And Health Checks

The dashboard now uses the selected repository backend.

- `DB_BACKEND=sqlite`: dashboard reads local SQLite stores.
- `DB_BACKEND=postgres`: dashboard reads PostgreSQL through `DATABASE_URL`.

After rebuilding the containers, verify:

```cmd
docker compose -f docker-compose.production.yml --env-file .env.production up -d --build
```

Open:

```text
http://localhost:8050/?token=<dashboard-token>
http://localhost:8050/api/health?token=<dashboard-token>
http://localhost:8050/api/optimize/irrigation?token=<dashboard-token>
```

Optional dashboard RBAC tokens:

```text
DASHBOARD_READ_TOKEN=read-token
DASHBOARD_WRITE_TOKEN=write-token
DASHBOARD_ADMIN_TOKEN=admin-token
```

If these are not set, `DASHBOARD_TOKEN` is used for read, write, and admin access.
