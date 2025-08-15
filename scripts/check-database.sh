#!/bin/bash
# Database health check and schema verification script

set -e

echo "Checking database schema integrity..."

# Required tables
REQUIRED_TABLES=(
    "collection_runs"
    "container_metrics"
    "agent_metrics"
    "deployment_metrics"
    "system_summaries"
)

# Check if PostgreSQL is running
if ! docker ps | grep -q ciris-postgres; then
    echo "ERROR: PostgreSQL container is not running"
    exit 1
fi

# Check if database is accessible
if ! docker exec ciris-postgres pg_isready -U ciris -d telemetry >/dev/null 2>&1; then
    echo "ERROR: Cannot connect to PostgreSQL"
    exit 1
fi

echo "PostgreSQL is running and accessible"

# Check for required tables
MISSING_TABLES=()
for table in "${REQUIRED_TABLES[@]}"; do
    if ! docker exec ciris-postgres psql -U ciris -d telemetry -tAc "SELECT 1 FROM pg_tables WHERE tablename='$table'" | grep -q 1; then
        MISSING_TABLES+=("$table")
    fi
done

if [ ${#MISSING_TABLES[@]} -gt 0 ]; then
    echo "ERROR: Missing required tables:"
    printf '%s\n' "${MISSING_TABLES[@]}"
    echo ""
    echo "To fix, run: docker exec -i ciris-postgres psql -U ciris -d telemetry < /opt/ciris-manager/deploy/init-telemetry-complete.sql"
    exit 1
fi

echo "✓ All required tables exist"

# Check for recent telemetry data
RECENT_COUNT=$(docker exec ciris-postgres psql -U ciris -d telemetry -tAc "SELECT COUNT(*) FROM collection_runs WHERE time > NOW() - INTERVAL '1 hour'" 2>/dev/null || echo 0)

if [ "$RECENT_COUNT" -gt 0 ]; then
    echo "✓ Found $RECENT_COUNT telemetry collections in the last hour"
else
    echo "⚠ No recent telemetry collections found"
fi

# Check for any errors in recent collections
ERROR_COUNT=$(docker exec ciris-postgres psql -U ciris -d telemetry -tAc "SELECT COUNT(*) FROM collection_runs WHERE success=false AND time > NOW() - INTERVAL '1 hour'" 2>/dev/null || echo 0)

if [ "$ERROR_COUNT" -gt 0 ]; then
    echo "⚠ Found $ERROR_COUNT failed collections in the last hour"
    echo "Recent errors:"
    docker exec ciris-postgres psql -U ciris -d telemetry -c "SELECT time, error_message FROM collection_runs WHERE success=false AND time > NOW() - INTERVAL '1 hour' ORDER BY time DESC LIMIT 5"
fi

echo ""
echo "Database health check complete"