-- Telemetry database schema with TimescaleDB optimizations
-- This creates all tables, hypertables, and continuous aggregates

\c telemetry;

-- Collection run metadata
CREATE TABLE IF NOT EXISTS collection_runs (
    snapshot_id UUID PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    duration_ms INTEGER NOT NULL,
    containers_collected INTEGER DEFAULT 0,
    agents_collected INTEGER DEFAULT 0,
    errors TEXT[],
    success BOOLEAN DEFAULT true
);

-- Container metrics
CREATE TABLE IF NOT EXISTS container_metrics (
    time TIMESTAMPTZ NOT NULL,
    container_id VARCHAR(64) NOT NULL,
    container_name VARCHAR(255),
    image VARCHAR(255),
    image_digest VARCHAR(255),
    status VARCHAR(20),
    health_status VARCHAR(20),
    restart_count INTEGER DEFAULT 0,
    cpu_percent DECIMAL(5,2),
    memory_mb INTEGER,
    memory_limit_mb INTEGER,
    memory_percent DECIMAL(5,2),
    disk_read_mb INTEGER,
    disk_write_mb INTEGER,
    network_rx_mb INTEGER,
    network_tx_mb INTEGER,
    created_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    exit_code INTEGER,
    error_message TEXT
);

-- Agent operational metrics
CREATE TABLE IF NOT EXISTS agent_metrics (
    time TIMESTAMPTZ NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    agent_name VARCHAR(255),
    version VARCHAR(50),
    cognitive_state VARCHAR(20),
    api_healthy BOOLEAN DEFAULT false,
    api_response_ms INTEGER,
    uptime_seconds INTEGER,
    incident_count_24h INTEGER DEFAULT 0,
    message_count_24h INTEGER DEFAULT 0,
    cost_cents_24h INTEGER DEFAULT 0,
    api_port INTEGER,
    oauth_configured BOOLEAN DEFAULT false,
    oauth_providers TEXT[]
);

-- Deployment tracking
CREATE TABLE IF NOT EXISTS deployments (
    deployment_id UUID PRIMARY KEY,
    status VARCHAR(20) NOT NULL,
    phase VARCHAR(20),
    agent_image VARCHAR(255),
    gui_image VARCHAR(255),
    nginx_image VARCHAR(255),
    agents_total INTEGER DEFAULT 0,
    agents_staged INTEGER DEFAULT 0,
    agents_updated INTEGER DEFAULT 0,
    agents_failed INTEGER DEFAULT 0,
    agents_deferred INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    staged_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    initiated_by VARCHAR(255),
    approved_by VARCHAR(255),
    is_rollback BOOLEAN DEFAULT false,
    rollback_from_deployment UUID
);

-- Version history
CREATE TABLE IF NOT EXISTS version_history (
    time TIMESTAMPTZ NOT NULL,
    component_type VARCHAR(20) NOT NULL,
    version_type VARCHAR(20) NOT NULL,
    image VARCHAR(255),
    digest VARCHAR(255),
    tag VARCHAR(50),
    deployed_at TIMESTAMPTZ,
    deployment_id UUID
);

-- Agent version adoption
CREATE TABLE IF NOT EXISTS agent_version_adoption (
    time TIMESTAMPTZ NOT NULL,
    agent_id VARCHAR(255) NOT NULL,
    agent_name VARCHAR(255),
    current_version VARCHAR(50),
    deployment_group VARCHAR(20),
    last_transition_at TIMESTAMPTZ,
    last_work_state_at TIMESTAMPTZ
);

-- System summaries (pre-aggregated)
CREATE TABLE IF NOT EXISTS system_summaries (
    time TIMESTAMPTZ NOT NULL PRIMARY KEY,
    agents_total INTEGER DEFAULT 0,
    agents_healthy INTEGER DEFAULT 0,
    agents_degraded INTEGER DEFAULT 0,
    agents_down INTEGER DEFAULT 0,
    agents_in_work INTEGER DEFAULT 0,
    agents_in_dream INTEGER DEFAULT 0,
    agents_in_solitude INTEGER DEFAULT 0,
    agents_in_play INTEGER DEFAULT 0,
    total_cpu_percent DECIMAL(10,2),
    total_memory_mb INTEGER,
    total_cost_cents_24h INTEGER,
    total_messages_24h INTEGER,
    total_incidents_24h INTEGER,
    active_deployments INTEGER DEFAULT 0,
    staged_deployments INTEGER DEFAULT 0,
    agents_on_latest INTEGER DEFAULT 0,
    agents_on_previous INTEGER DEFAULT 0,
    agents_on_older INTEGER DEFAULT 0
);

-- Convert to hypertables for time-series optimization
SELECT create_hypertable('container_metrics', 'time', if_not_exists => TRUE);
SELECT create_hypertable('agent_metrics', 'time', if_not_exists => TRUE);
SELECT create_hypertable('version_history', 'time', if_not_exists => TRUE);
SELECT create_hypertable('agent_version_adoption', 'time', if_not_exists => TRUE);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_container_metrics_container_id ON container_metrics (container_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_agent_id ON agent_metrics (agent_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_deployments_status ON deployments (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_version_history_component ON version_history (component_type, time DESC);

-- Continuous aggregate for 5-minute container stats
CREATE MATERIALIZED VIEW IF NOT EXISTS container_stats_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    container_name,
    AVG(cpu_percent) AS avg_cpu,
    MAX(cpu_percent) AS max_cpu,
    AVG(memory_mb) AS avg_memory_mb,
    MAX(memory_mb) AS max_memory_mb,
    AVG(memory_percent) AS avg_memory_percent,
    COUNT(*) AS sample_count
FROM container_metrics
GROUP BY bucket, container_name
WITH NO DATA;

-- Continuous aggregate for hourly agent stats
CREATE MATERIALIZED VIEW IF NOT EXISTS agent_stats_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    agent_id,
    agent_name,
    mode() WITHIN GROUP (ORDER BY cognitive_state) AS dominant_state,
    AVG(api_response_ms) AS avg_response_ms,
    SUM(message_count_24h) AS total_messages,
    SUM(incident_count_24h) AS total_incidents,
    SUM(cost_cents_24h) AS total_cost_cents,
    COUNT(*) AS sample_count
FROM agent_metrics
GROUP BY bucket, agent_id, agent_name
WITH NO DATA;

-- Refresh policies for continuous aggregates
SELECT add_continuous_aggregate_policy('container_stats_5min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE);

SELECT add_continuous_aggregate_policy('agent_stats_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE);

-- Data retention policies
SELECT add_retention_policy('container_metrics', 
    drop_after => INTERVAL '7 days',
    if_not_exists => TRUE);

SELECT add_retention_policy('agent_metrics', 
    drop_after => INTERVAL '30 days',
    if_not_exists => TRUE);

-- Compression policies for older data
SELECT add_compression_policy('container_metrics', 
    compress_after => INTERVAL '1 day',
    if_not_exists => TRUE);

SELECT add_compression_policy('agent_metrics', 
    compress_after => INTERVAL '3 days',
    if_not_exists => TRUE);

-- Grant permissions to application user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO telemetry_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO telemetry_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO telemetry_app;