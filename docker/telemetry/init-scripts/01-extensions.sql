-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Configure TimescaleDB
SELECT timescaledb_pre_restore();

-- Set up performance tuning
ALTER SYSTEM SET shared_preload_libraries = 'timescaledb,pg_cron,pg_stat_statements';
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '128MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = 100;
ALTER SYSTEM SET random_page_cost = 1.1;
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET work_mem = '4MB';
ALTER SYSTEM SET min_wal_size = '1GB';
ALTER SYSTEM SET max_wal_size = '2GB';

-- TimescaleDB specific settings
ALTER SYSTEM SET timescaledb.max_background_workers = 8;
ALTER SYSTEM SET timescaledb.telemetry_level = 'basic';

SELECT timescaledb_post_restore();

-- Create telemetry user if not exists
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'telemetry_app') THEN
        CREATE USER telemetry_app WITH PASSWORD 'changeme';
    END IF;
END
$$;

-- Grant permissions
GRANT CONNECT ON DATABASE telemetry TO telemetry_app;
GRANT USAGE ON SCHEMA public TO telemetry_app;
GRANT CREATE ON SCHEMA public TO telemetry_app;