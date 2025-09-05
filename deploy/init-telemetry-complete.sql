-- Complete telemetry database schema for CIRISManager
-- This script ensures all required tables and indexes exist

-- Create extension for UUID generation if not exists
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Collection runs table (for tracking telemetry collection runs)
CREATE TABLE IF NOT EXISTS collection_runs (
    run_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snapshot_id UUID UNIQUE,
    time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT false,
    error_message TEXT,
    containers_collected INTEGER DEFAULT 0,
    agents_collected INTEGER DEFAULT 0,
    deployments_collected INTEGER DEFAULT 0,
    errors JSONB,
    collector_version VARCHAR(50)
);

-- Create indexes for collection_runs
CREATE INDEX IF NOT EXISTS idx_collection_runs_time ON collection_runs(time DESC);
CREATE INDEX IF NOT EXISTS idx_collection_runs_snapshot ON collection_runs(snapshot_id);

-- Container metrics table
CREATE TABLE IF NOT EXISTS container_metrics (
    id SERIAL PRIMARY KEY,
    snapshot_id UUID,
    time TIMESTAMPTZ NOT NULL,
    container_id VARCHAR(64) NOT NULL,
    container_name VARCHAR(255) NOT NULL,
    image TEXT NOT NULL,
    image_digest VARCHAR(128),
    status VARCHAR(20) NOT NULL,
    health_status VARCHAR(20),
    cpu_percent DECIMAL(10,2) DEFAULT 0,
    memory_mb INTEGER DEFAULT 0,
    memory_limit_mb INTEGER,
    memory_percent DECIMAL(5,2),
    disk_read_mb BIGINT DEFAULT 0,
    disk_write_mb BIGINT DEFAULT 0,
    network_rx_mb BIGINT DEFAULT 0,
    network_tx_mb BIGINT DEFAULT 0,
    restart_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    exit_code INTEGER,
    error_message TEXT
);

-- Create indexes for container_metrics
CREATE INDEX IF NOT EXISTS idx_container_metrics_snapshot ON container_metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_container_metrics_time ON container_metrics(time DESC);
CREATE INDEX IF NOT EXISTS idx_container_metrics_container ON container_metrics(container_id, time DESC);

-- Agent metrics table
CREATE TABLE IF NOT EXISTS agent_metrics (
    id SERIAL PRIMARY KEY,
    snapshot_id UUID NOT NULL,
    time TIMESTAMPTZ NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    agent_name VARCHAR(255) NOT NULL,
    version VARCHAR(50),
    api_port INTEGER,
    cognitive_state VARCHAR(20),
    api_healthy BOOLEAN DEFAULT false,
    api_response_time_ms INTEGER,
    uptime_seconds INTEGER,
    incident_count_24h INTEGER DEFAULT 0,
    message_count_24h INTEGER DEFAULT 0,
    cost_cents_24h INTEGER DEFAULT 0,
    carbon_24h_grams INTEGER DEFAULT 0,
    oauth_configured BOOLEAN DEFAULT false,
    oauth_providers TEXT[]
);

-- Create indexes for agent_metrics
CREATE INDEX IF NOT EXISTS idx_agent_metrics_snapshot ON agent_metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_time ON agent_metrics(time DESC);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_agent ON agent_metrics(agent_id, time DESC);

-- Deployment metrics table
CREATE TABLE IF NOT EXISTS deployment_metrics (
    id SERIAL PRIMARY KEY,
    snapshot_id UUID NOT NULL,
    time TIMESTAMPTZ NOT NULL,
    deployment_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    strategy VARCHAR(50),
    agents_total INTEGER DEFAULT 0,
    agents_updated INTEGER DEFAULT 0,
    agents_deferred INTEGER DEFAULT 0,
    agents_failed INTEGER DEFAULT 0,
    canary_phase VARCHAR(50),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    message TEXT
);

-- Create indexes for deployment_metrics
CREATE INDEX IF NOT EXISTS idx_deployment_metrics_snapshot ON deployment_metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_deployment_metrics_time ON deployment_metrics(time DESC);
CREATE INDEX IF NOT EXISTS idx_deployment_metrics_deployment ON deployment_metrics(deployment_id);

-- System summaries table (aggregated metrics)
CREATE TABLE IF NOT EXISTS system_summaries (
    id SERIAL PRIMARY KEY,
    run_id UUID REFERENCES collection_runs(run_id) ON DELETE CASCADE,
    time TIMESTAMPTZ NOT NULL,
    total_agents INTEGER DEFAULT 0,
    agents_healthy INTEGER DEFAULT 0,
    agents_degraded INTEGER DEFAULT 0,
    agents_down INTEGER DEFAULT 0,
    agents_in_work INTEGER DEFAULT 0,
    agents_in_dream INTEGER DEFAULT 0,
    agents_in_solitude INTEGER DEFAULT 0,
    agents_in_play INTEGER DEFAULT 0,
    total_cpu_percent DECIMAL(10,2) DEFAULT 0,
    total_memory_mb INTEGER DEFAULT 0,
    total_messages_24h INTEGER DEFAULT 0,
    total_cost_cents_24h INTEGER DEFAULT 0,
    total_incidents_24h INTEGER DEFAULT 0,
    total_carbon_24h_grams INTEGER DEFAULT 0
);

-- Create indexes for system_summaries
CREATE INDEX IF NOT EXISTS idx_system_summaries_run ON system_summaries(run_id);
CREATE INDEX IF NOT EXISTS idx_system_summaries_time ON system_summaries(time DESC);

-- Grant permissions to ciris user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ciris;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ciris;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO ciris;

-- Create views for easy querying
CREATE OR REPLACE VIEW telemetry_latest AS
SELECT
    cr.time as collection_time,
    cr.success,
    cr.containers_collected,
    cr.agents_collected,
    ss.total_agents,
    ss.agents_healthy,
    ss.total_messages_24h,
    ss.total_cost_cents_24h
FROM collection_runs cr
LEFT JOIN system_summaries ss ON cr.run_id = ss.run_id
ORDER BY cr.time DESC
LIMIT 100;

-- Grant view permissions
GRANT SELECT ON telemetry_latest TO ciris;
