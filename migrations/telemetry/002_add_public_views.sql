-- Migration: 002_add_public_views
-- Description: Add public-safe views for telemetry data
-- Date: 2025-08-13

BEGIN;

-- Check if migration has been applied
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = 2) THEN
        RAISE NOTICE 'Migration 002 already applied, skipping';
        RETURN;
    END IF;
END
$$;

-- Public status view (no sensitive data)
CREATE OR REPLACE VIEW public_telemetry_status AS
SELECT
    NOW() as current_time,
    COUNT(DISTINCT agent_id) as total_agents,
    COUNT(DISTINCT CASE WHEN api_healthy THEN agent_id END) as healthy_agents,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN api_healthy THEN agent_id END) / 
          NULLIF(COUNT(DISTINCT agent_id), 0), 1) as health_percentage,
    SUM(message_count_24h) as total_messages_24h,
    SUM(incident_count_24h) as total_incidents_24h,
    COUNT(DISTINCT CASE WHEN cognitive_state = 'WORK' THEN agent_id END) as agents_working,
    COUNT(DISTINCT CASE WHEN cognitive_state = 'DREAM' THEN agent_id END) as agents_dreaming
FROM agent_metrics
WHERE time > NOW() - INTERVAL '5 minutes';

-- Public history view (aggregated only)
CREATE OR REPLACE VIEW public_telemetry_history AS
SELECT
    time_bucket('5 minutes', time) as bucket,
    COUNT(DISTINCT agent_id) as agent_count,
    ROUND(AVG(CASE WHEN api_healthy THEN 100 ELSE 0 END), 1) as health_percentage,
    SUM(message_count_24h) as messages_total,
    SUM(incident_count_24h) as incidents_total
FROM agent_metrics
WHERE time > NOW() - INTERVAL '24 hours'
GROUP BY bucket
ORDER BY bucket DESC;

-- Public deployment status (no specifics)
CREATE OR REPLACE VIEW public_deployment_status AS
SELECT
    CASE 
        WHEN COUNT(*) FILTER (WHERE status IN ('in_progress', 'rolling_back')) > 0 
        THEN 'active'
        WHEN COUNT(*) FILTER (WHERE status = 'staged') > 0
        THEN 'staged'
        ELSE 'idle'
    END as deployment_state,
    COUNT(*) FILTER (WHERE status IN ('in_progress', 'rolling_back')) as active_deployments,
    COUNT(*) FILTER (WHERE status = 'completed' AND completed_at > NOW() - INTERVAL '24 hours') as recent_completions,
    MAX(completed_at) as last_deployment
FROM deployments;

-- Grant read access to public views
GRANT SELECT ON public_telemetry_status TO telemetry_app;
GRANT SELECT ON public_telemetry_history TO telemetry_app;
GRANT SELECT ON public_deployment_status TO telemetry_app;

-- Record migration
INSERT INTO schema_migrations (version, name) VALUES (2, '002_add_public_views');

COMMIT;