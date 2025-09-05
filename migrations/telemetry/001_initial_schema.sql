-- Migration: 001_initial_schema
-- Description: Initial telemetry database schema
-- Date: 2025-08-13

BEGIN;

-- Migration tracking table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);

-- Check if this migration has been applied
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM schema_migrations WHERE version = 1) THEN
        RAISE NOTICE 'Migration 001 already applied, skipping';
        RETURN;
    END IF;

    -- Apply migration
    RAISE NOTICE 'Applying migration 001: Initial schema';
END
$$;

-- Only create schema if migration hasn't been applied
INSERT INTO schema_migrations (version, name)
SELECT 1, '001_initial_schema'
WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 1);

COMMIT;
