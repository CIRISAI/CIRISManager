-- Create telemetry schema
CREATE SCHEMA IF NOT EXISTS telemetry;

-- Telemetry snapshots table
CREATE TABLE IF NOT EXISTS telemetry.snapshots (
    snapshot_id UUID PRIMARY KEY,
    collection_time TIMESTAMPTZ NOT NULL,
    collection_duration_ms INTEGER,

    -- Summary metrics
    total_agents INTEGER DEFAULT 0,
    agents_healthy INTEGER DEFAULT 0,
    agents_degraded INTEGER DEFAULT 0,
    agents_down INTEGER DEFAULT 0,

    -- Cognitive states
    agents_in_work INTEGER DEFAULT 0,
    agents_in_dream INTEGER DEFAULT 0,
    agents_in_solitude INTEGER DEFAULT 0,
    agents_in_play INTEGER DEFAULT 0,

    -- Resource metrics
    total_cpu_percent REAL DEFAULT 0,
    total_memory_mb REAL DEFAULT 0,

    -- Business metrics
    total_messages_24h INTEGER DEFAULT 0,
    total_cost_cents_24h INTEGER DEFAULT 0,
    total_incidents_24h INTEGER DEFAULT 0,

    -- Raw data
    container_metrics JSONB,
    agent_metrics JSONB,
    deployment_metrics JSONB,
    version_tracking JSONB,
    errors JSONB,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_snapshots_collection_time
ON telemetry.snapshots(collection_time DESC);

-- Public history view (aggregated for dashboard)
CREATE OR REPLACE VIEW telemetry.public_history AS
SELECT
    collection_time as timestamp,
    total_agents,
    agents_healthy as healthy_agents,
    total_messages_24h as total_messages,
    total_incidents_24h as total_incidents
FROM telemetry.snapshots
ORDER BY collection_time DESC;

-- Grant permissions
GRANT USAGE ON SCHEMA telemetry TO ciris;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA telemetry TO ciris;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA telemetry TO ciris;
