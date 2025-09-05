#!/bin/bash
# Initialize telemetry system for CIRISManager
# This script ensures telemetry is properly set up on new deployments

set -e

echo "=== CIRISManager Telemetry Initialization ==="
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root or with sudo"
    exit 1
fi

# Configuration
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-ciris-postgres}"
POSTGRES_USER="${POSTGRES_USER:-ciris}"
POSTGRES_DB="${POSTGRES_DB:-telemetry}"
MANAGER_DIR="${MANAGER_DIR:-/opt/ciris-manager}"
AGENTS_DIR="${AGENTS_DIR:-/opt/ciris/agents}"

echo "1. Checking PostgreSQL container..."
if ! docker ps --format '{{.Names}}' | grep -q "^${POSTGRES_CONTAINER}$"; then
    echo "   ✗ PostgreSQL container '${POSTGRES_CONTAINER}' not found"
    echo "   Creating PostgreSQL container..."
    docker run -d \
        --name "${POSTGRES_CONTAINER}" \
        --restart unless-stopped \
        -e POSTGRES_USER="${POSTGRES_USER}" \
        -e POSTGRES_PASSWORD="ciris_telemetry_2024" \
        -e POSTGRES_DB="${POSTGRES_DB}" \
        -v ciris_postgres_data:/var/lib/postgresql/data \
        -p 127.0.0.1:5432:5432 \
        postgres:15-alpine

    echo "   Waiting for PostgreSQL to start..."
    sleep 10
else
    echo "   ✓ PostgreSQL container found"
fi

echo ""
echo "2. Creating database schema..."

# Create a temporary SQL file without TimescaleDB requirements
cat > /tmp/telemetry_schema.sql << 'EOF'
-- PostgreSQL schema for CIRIS telemetry (without TimescaleDB)

-- Collection runs table
CREATE TABLE IF NOT EXISTS collection_runs (
    run_id          UUID PRIMARY KEY,
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,
    duration_ms     INTEGER,
    success         BOOLEAN NOT NULL DEFAULT false,
    error_message   TEXT,

    -- Counts
    containers_collected    INTEGER DEFAULT 0,
    agents_collected       INTEGER DEFAULT 0,
    deployments_collected  INTEGER DEFAULT 0,

    -- Metadata
    collector_version      VARCHAR(50),

    -- Index for time-based queries
    CONSTRAINT collection_runs_start_time_idx UNIQUE (start_time)
);

-- System summaries table
CREATE TABLE IF NOT EXISTS system_summaries (
    summary_id      UUID PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    run_id          UUID REFERENCES collection_runs(run_id) ON DELETE CASCADE,

    -- Agent counts
    agents_total    INTEGER NOT NULL DEFAULT 0,
    agents_healthy  INTEGER NOT NULL DEFAULT 0,
    agents_degraded INTEGER NOT NULL DEFAULT 0,
    agents_down     INTEGER NOT NULL DEFAULT 0,

    -- Cognitive states
    agents_in_work      INTEGER NOT NULL DEFAULT 0,
    agents_in_dream     INTEGER NOT NULL DEFAULT 0,
    agents_in_solitude  INTEGER NOT NULL DEFAULT 0,
    agents_in_play      INTEGER NOT NULL DEFAULT 0,

    -- Resources
    total_cpu_percent       DECIMAL(10,2) NOT NULL DEFAULT 0,
    total_memory_mb        INTEGER NOT NULL DEFAULT 0,
    total_cost_cents_24h   INTEGER NOT NULL DEFAULT 0,

    -- Activity
    total_messages_24h     INTEGER NOT NULL DEFAULT 0,
    total_incidents_24h    INTEGER NOT NULL DEFAULT 0,

    -- Deployments
    active_deployments     INTEGER NOT NULL DEFAULT 0,
    staged_deployments     INTEGER NOT NULL DEFAULT 0,

    -- Version adoption
    agents_on_latest       INTEGER NOT NULL DEFAULT 0,
    agents_on_previous     INTEGER NOT NULL DEFAULT 0,
    agents_on_older        INTEGER NOT NULL DEFAULT 0
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_summaries_timestamp ON system_summaries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_collection_runs_start ON collection_runs(start_time DESC);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${POSTGRES_USER};
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${POSTGRES_USER};
EOF

# Apply schema
docker exec -i "${POSTGRES_CONTAINER}" psql -U "${POSTGRES_USER}" "${POSTGRES_DB}" < /tmp/telemetry_schema.sql 2>/dev/null || {
    echo "   ⚠ Schema already exists or minor errors (this is OK)"
}
echo "   ✓ Database schema ready"

echo ""
echo "3. Checking service tokens..."

# Check if environment variables are set
if [ -z "$CIRIS_ENCRYPTION_KEY" ] || [ -z "$MANAGER_JWT_SECRET" ]; then
    echo "   ⚠ Environment variables not set. Loading from systemd service..."

    # Extract from systemd service if it exists
    if [ -f /etc/systemd/system/ciris-manager.service ]; then
        export CIRIS_ENCRYPTION_KEY=$(grep "Environment=\"CIRIS_ENCRYPTION_KEY=" /etc/systemd/system/ciris-manager.service | cut -d'"' -f2 | cut -d'=' -f2)
        export MANAGER_JWT_SECRET=$(grep "Environment=\"MANAGER_JWT_SECRET=" /etc/systemd/system/ciris-manager.service | cut -d'"' -f2 | cut -d'=' -f2)
    fi

    # Use defaults if still not set
    export CIRIS_ENCRYPTION_KEY="${CIRIS_ENCRYPTION_KEY:-_AFlp77JRC55GooNp4BxfS7jIuDWlbhzJcRxPzjE00E=}"
    export MANAGER_JWT_SECRET="${MANAGER_JWT_SECRET:-a1b2c3d4e5f6789012345678901234567890123456789012345678901234567}"
fi

# Recover tokens from running containers
cd "${MANAGER_DIR}"
if [ -f venv/bin/activate ]; then
    source venv/bin/activate

    echo "   Recovering tokens from containers..."
    ciris-manager tokens recover || echo "   ⚠ Some tokens could not be recovered"

    echo "   Verifying tokens..."
    ciris-manager tokens list
else
    echo "   ⚠ Virtual environment not found, skipping token recovery"
fi

echo ""
echo "4. Restarting CIRISManager service..."
systemctl restart ciris-manager || {
    echo "   ⚠ Failed to restart service, trying manual start..."
    cd "${MANAGER_DIR}"
    source venv/bin/activate
    nohup ciris-manager --config /etc/ciris-manager/config.yml > /var/log/ciris-manager.log 2>&1 &
}

echo ""
echo "5. Verifying telemetry collection..."
sleep 15  # Wait for first collection cycle

# Check telemetry status
curl -s http://localhost:8888/manager/v1/telemetry/status | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'   Agents: {data.get(\"agents_total\", 0)} total, {data.get(\"agents_healthy\", 0)} healthy')
print(f'   Cost (24h): {data.get(\"total_cost_cents_24h\", 0)} cents')
print(f'   Messages (24h): {data.get(\"total_messages_24h\", 0)}')
" 2>/dev/null || echo "   ⚠ Could not verify telemetry status"

echo ""
echo "=== Telemetry initialization complete ==="
echo ""
echo "Dashboard available at: http://$(hostname -I | awk '{print $1}'):8888/dashboard"
echo "API status: http://localhost:8888/manager/v1/telemetry/status"
