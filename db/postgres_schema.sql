-- PostgreSQL/TimescaleDB production schema for Agentic AI Fog cloud services.
-- SQLite remains the local/demo backend. This schema is the production target.

CREATE TABLE IF NOT EXISTS fog_events (
    event_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sensor_id TEXT,
    zone_id TEXT,
    scenario TEXT,
    severity TEXT,
    critical BOOLEAN NOT NULL DEFAULT FALSE,
    decision TEXT,
    result TEXT,
    payload_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fog_events_created_at ON fog_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fog_events_topic ON fog_events(topic);
CREATE INDEX IF NOT EXISTS idx_fog_events_zone ON fog_events(zone_id);
CREATE INDEX IF NOT EXISTS idx_fog_events_sensor ON fog_events(sensor_id);

CREATE TABLE IF NOT EXISTS twin_events (
    event_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    event_json JSONB NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS zone_state (
    zone_id TEXT PRIMARY KEY,
    last_sensor_id TEXT,
    scenario TEXT,
    severity TEXT,
    critical BOOLEAN NOT NULL DEFAULT FALSE,
    decision TEXT,
    result TEXT,
    trust_score DOUBLE PRECISION,
    risk_index DOUBLE PRECISION,
    soil_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    crop_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    dynamic_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    context_summary TEXT,
    multimodal_summary TEXT,
    state_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS human_feedback (
    feedback_id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    sensor_id TEXT,
    reviewer_id TEXT NOT NULL,
    label TEXT NOT NULL,
    scenario TEXT,
    corrected_action TEXT,
    notes TEXT,
    confidence DOUBLE PRECISION,
    feedback_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS calibration_profiles (
    profile_id BIGSERIAL PRIMARY KEY,
    farm_id TEXT NOT NULL,
    source TEXT NOT NULL,
    profile_json JSONB NOT NULL,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calibration_profiles_farm_active ON calibration_profiles(farm_id, active);

CREATE TABLE IF NOT EXISTS policy_versions (
    policy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    rules_json JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (policy_id, version)
);

CREATE TABLE IF NOT EXISTS model_versions (
    version TEXT PRIMARY KEY,
    checksum_sha256 TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Optional TimescaleDB migration, if extension is installed:
-- CREATE EXTENSION IF NOT EXISTS timescaledb;
-- SELECT create_hypertable('fog_events', 'created_at', if_not_exists => TRUE);
-- SELECT create_hypertable('twin_events', 'applied_at', if_not_exists => TRUE);
