-- PostgreSQL/TimescaleDB schema for CIRIS telemetry
-- 
-- This schema uses TimescaleDB for efficient time-series storage
-- with automatic partitioning and retention policies.

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ============================================================================
-- CONTAINER METRICS
-- ============================================================================

-- Container metrics time-series table
CREATE TABLE IF NOT EXISTS container_metrics (
    time            TIMESTAMPTZ NOT NULL,
    container_id    VARCHAR(64) NOT NULL,
    container_name  VARCHAR(255) NOT NULL,
    image           TEXT NOT NULL,
    image_digest    VARCHAR(128),
    
    -- Status
    status          VARCHAR(20) NOT NULL,
    health_status   VARCHAR(20) NOT NULL,
    restart_count   INTEGER NOT NULL DEFAULT 0,
    
    -- Resources
    cpu_percent     DECIMAL(10,2) NOT NULL CHECK (cpu_percent >= 0),
    memory_mb       INTEGER NOT NULL CHECK (memory_mb >= 0),
    memory_limit_mb INTEGER,
    memory_percent  DECIMAL(5,2) CHECK (memory_percent >= 0 AND memory_percent <= 100),
    disk_read_mb    BIGINT NOT NULL DEFAULT 0,
    disk_write_mb   BIGINT NOT NULL DEFAULT 0,
    network_rx_mb   BIGINT NOT NULL DEFAULT 0,
    network_tx_mb   BIGINT NOT NULL DEFAULT 0,
    
    -- Lifecycle
    created_at      TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    exit_code       INTEGER,
    error_message   TEXT
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('container_metrics', 'time', 
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Create indices for common queries
CREATE INDEX IF NOT EXISTS idx_container_metrics_name_time 
    ON container_metrics (container_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_container_metrics_status 
    ON container_metrics (status, time DESC);

-- ============================================================================
-- AGENT OPERATIONAL METRICS
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_metrics (
    time                TIMESTAMPTZ NOT NULL,
    agent_id            VARCHAR(255) NOT NULL,
    agent_name          VARCHAR(255) NOT NULL,
    
    -- Version and state
    version             VARCHAR(50) NOT NULL,
    cognitive_state     VARCHAR(20) NOT NULL,
    
    -- Health
    api_healthy         BOOLEAN NOT NULL,
    api_response_ms     INTEGER CHECK (api_response_ms >= 0),
    
    -- Operational metrics
    uptime_seconds      BIGINT NOT NULL CHECK (uptime_seconds >= 0),
    incident_count_24h  INTEGER NOT NULL DEFAULT 0,
    message_count_24h   INTEGER NOT NULL DEFAULT 0,
    cost_cents_24h      INTEGER NOT NULL DEFAULT 0,
    
    -- Configuration
    api_port            INTEGER NOT NULL CHECK (api_port > 0 AND api_port <= 65535),
    oauth_configured    BOOLEAN NOT NULL DEFAULT FALSE,
    oauth_providers     TEXT[] DEFAULT '{}'
);

SELECT create_hypertable('agent_metrics', 'time',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_agent_metrics_name_time 
    ON agent_metrics (agent_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_state 
    ON agent_metrics (cognitive_state, time DESC);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_health 
    ON agent_metrics (api_healthy, time DESC);

-- ============================================================================
-- DEPLOYMENT TRACKING
-- ============================================================================

-- Deployment events (not time-series, but event-based)
CREATE TABLE IF NOT EXISTS deployments (
    deployment_id           VARCHAR(255) PRIMARY KEY,
    status                  VARCHAR(20) NOT NULL,
    phase                   VARCHAR(20),
    
    -- Images being deployed
    agent_image             TEXT,
    gui_image               TEXT,
    nginx_image             TEXT,
    
    -- Progress
    agents_total            INTEGER NOT NULL DEFAULT 0,
    agents_staged           INTEGER NOT NULL DEFAULT 0,
    agents_updated          INTEGER NOT NULL DEFAULT 0,
    agents_failed           INTEGER NOT NULL DEFAULT 0,
    agents_deferred         INTEGER NOT NULL DEFAULT 0,
    
    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL,
    staged_at               TIMESTAMPTZ,
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    
    -- Metadata
    initiated_by            VARCHAR(255),
    approved_by             VARCHAR(255),
    is_rollback             BOOLEAN NOT NULL DEFAULT FALSE,
    rollback_from_deployment VARCHAR(255),
    
    FOREIGN KEY (rollback_from_deployment) REFERENCES deployments(deployment_id)
);

CREATE INDEX IF NOT EXISTS idx_deployments_status 
    ON deployments (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deployments_active 
    ON deployments (status) WHERE status IN ('in_progress', 'staged', 'rolling_back');

-- ============================================================================
-- VERSION TRACKING
-- ============================================================================

-- Component version history
CREATE TABLE IF NOT EXISTS version_history (
    time            TIMESTAMPTZ NOT NULL,
    component_type  VARCHAR(20) NOT NULL, -- agent, gui, nginx, manager
    version_type    VARCHAR(20) NOT NULL, -- current, previous, fallback, staged
    
    image           TEXT NOT NULL,
    digest          VARCHAR(128),
    tag             VARCHAR(50) NOT NULL,
    deployed_at     TIMESTAMPTZ NOT NULL,
    deployment_id   VARCHAR(255),
    
    FOREIGN KEY (deployment_id) REFERENCES deployments(deployment_id)
);

SELECT create_hypertable('version_history', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_version_history_component 
    ON version_history (component_type, time DESC);

-- Agent version adoption tracking
CREATE TABLE IF NOT EXISTS agent_version_adoption (
    time                TIMESTAMPTZ NOT NULL,
    agent_id            VARCHAR(255) NOT NULL,
    agent_name          VARCHAR(255) NOT NULL,
    current_version     VARCHAR(50) NOT NULL,
    deployment_group    VARCHAR(20) NOT NULL, -- explorers, early_adopters, general
    last_transition_at  TIMESTAMPTZ,
    last_work_state_at  TIMESTAMPTZ
);

SELECT create_hypertable('agent_version_adoption', 'time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_agent_adoption_name 
    ON agent_version_adoption (agent_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_agent_adoption_group 
    ON agent_version_adoption (deployment_group, time DESC);

-- ============================================================================
-- AGGREGATED SUMMARIES
-- ============================================================================

-- System-wide summaries for dashboard
CREATE TABLE IF NOT EXISTS system_summaries (
    time                    TIMESTAMPTZ NOT NULL PRIMARY KEY,
    
    -- Agent counts
    agents_total            INTEGER NOT NULL DEFAULT 0,
    agents_healthy          INTEGER NOT NULL DEFAULT 0,
    agents_degraded         INTEGER NOT NULL DEFAULT 0,
    agents_down             INTEGER NOT NULL DEFAULT 0,
    
    -- Cognitive states
    agents_in_work          INTEGER NOT NULL DEFAULT 0,
    agents_in_dream         INTEGER NOT NULL DEFAULT 0,
    agents_in_solitude      INTEGER NOT NULL DEFAULT 0,
    agents_in_play          INTEGER NOT NULL DEFAULT 0,
    
    -- Resources
    total_cpu_percent       DECIMAL(10,2) NOT NULL DEFAULT 0,
    total_memory_mb         BIGINT NOT NULL DEFAULT 0,
    total_cost_cents_24h    BIGINT NOT NULL DEFAULT 0,
    
    -- Activity
    total_messages_24h      BIGINT NOT NULL DEFAULT 0,
    total_incidents_24h     INTEGER NOT NULL DEFAULT 0,
    
    -- Deployments
    active_deployments      INTEGER NOT NULL DEFAULT 0,
    staged_deployments      INTEGER NOT NULL DEFAULT 0,
    
    -- Version adoption
    agents_on_latest        INTEGER NOT NULL DEFAULT 0,
    agents_on_previous      INTEGER NOT NULL DEFAULT 0,
    agents_on_older         INTEGER NOT NULL DEFAULT 0
);

-- Not a hypertable since we keep limited history
CREATE INDEX IF NOT EXISTS idx_summaries_time 
    ON system_summaries (time DESC);

-- ============================================================================
-- TELEMETRY METADATA
-- ============================================================================

-- Track collection runs and errors
CREATE TABLE IF NOT EXISTS collection_runs (
    snapshot_id         UUID PRIMARY KEY,
    time                TIMESTAMPTZ NOT NULL,
    duration_ms         INTEGER NOT NULL,
    containers_collected INTEGER NOT NULL DEFAULT 0,
    agents_collected    INTEGER NOT NULL DEFAULT 0,
    errors              TEXT[] DEFAULT '{}',
    success             BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_collection_runs_time 
    ON collection_runs (time DESC);

-- ============================================================================
-- CONTINUOUS AGGREGATES (TimescaleDB feature)
-- ============================================================================

-- 5-minute aggregates for container metrics
CREATE MATERIALIZED VIEW IF NOT EXISTS container_metrics_5min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    container_name,
    AVG(cpu_percent) as avg_cpu,
    MAX(cpu_percent) as max_cpu,
    AVG(memory_mb) as avg_memory_mb,
    MAX(memory_mb) as max_memory_mb,
    AVG(memory_percent) as avg_memory_percent
FROM container_metrics
GROUP BY bucket, container_name
WITH NO DATA;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('container_metrics_5min',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);

-- Hourly aggregates for agent metrics
CREATE MATERIALIZED VIEW IF NOT EXISTS agent_metrics_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    agent_name,
    mode() WITHIN GROUP (ORDER BY cognitive_state) as dominant_state,
    AVG(CASE WHEN api_healthy THEN 1 ELSE 0 END) * 100 as uptime_percent,
    SUM(message_count_24h) / 24 as messages_per_hour,
    SUM(incident_count_24h) / 24 as incidents_per_hour,
    AVG(api_response_ms) as avg_response_ms
FROM agent_metrics
GROUP BY bucket, agent_name
WITH NO DATA;

SELECT add_continuous_aggregate_policy('agent_metrics_hourly',
    start_offset => INTERVAL '2 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- ============================================================================
-- RETENTION POLICIES
-- ============================================================================

-- Keep raw metrics for 7 days
SELECT add_retention_policy('container_metrics', 
    INTERVAL '7 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy('agent_metrics',
    INTERVAL '7 days', 
    if_not_exists => TRUE
);

-- Keep version history for 30 days
SELECT add_retention_policy('version_history',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

SELECT add_retention_policy('agent_version_adoption',
    INTERVAL '30 days',
    if_not_exists => TRUE
);

-- Keep summaries for 90 days
-- (Note: system_summaries is not a hypertable, so we'd handle this differently)

-- Keep collection metadata for 30 days
-- (Note: collection_runs is not a hypertable, so we'd handle this differently)

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get latest system status
CREATE OR REPLACE FUNCTION get_latest_system_status()
RETURNS TABLE (
    total_agents INTEGER,
    healthy_agents INTEGER,
    total_cpu DECIMAL,
    total_memory_mb BIGINT,
    messages_24h BIGINT,
    incidents_24h INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        agents_total,
        agents_healthy,
        total_cpu_percent,
        total_memory_mb,
        total_messages_24h,
        total_incidents_24h
    FROM system_summaries
    ORDER BY time DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to get agent health timeline
CREATE OR REPLACE FUNCTION get_agent_health_timeline(
    p_agent_name VARCHAR(255),
    p_hours INTEGER DEFAULT 24
)
RETURNS TABLE (
    time TIMESTAMPTZ,
    healthy BOOLEAN,
    cognitive_state VARCHAR(20),
    response_ms INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        am.time,
        am.api_healthy,
        am.cognitive_state,
        am.api_response_ms
    FROM agent_metrics am
    WHERE am.agent_name = p_agent_name
        AND am.time > NOW() - (p_hours || ' hours')::INTERVAL
    ORDER BY am.time DESC;
END;
$$ LANGUAGE plpgsql;