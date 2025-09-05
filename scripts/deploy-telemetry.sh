#!/bin/bash
# Telemetry system deployment script
# This script handles the complete deployment of the telemetry system

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env.telemetry"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Load environment variables
load_env() {
    if [ -f "$ENV_FILE" ]; then
        log_info "Loading environment from $ENV_FILE"
        export $(cat "$ENV_FILE" | grep -v '^#' | xargs)
    else
        log_error "Environment file not found: $ENV_FILE"
        exit 1
    fi
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    # Check PostgreSQL client
    if ! command -v psql &> /dev/null; then
        log_warning "PostgreSQL client not installed, installing..."
        sudo apt-get update && sudo apt-get install -y postgresql-client
    fi

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    log_success "All prerequisites met"
}

# Deploy database
deploy_database() {
    log_info "Deploying TimescaleDB..."

    # Check if container exists
    if docker ps -a --format '{{.Names}}' | grep -q '^timescaledb$'; then
        log_info "TimescaleDB container already exists"

        # Check if running
        if ! docker ps --format '{{.Names}}' | grep -q '^timescaledb$'; then
            log_info "Starting TimescaleDB container..."
            docker start timescaledb
        fi
    else
        log_info "Creating TimescaleDB container..."
        docker run -d \
            --name timescaledb \
            --restart unless-stopped \
            -p ${TELEMETRY_DB_PORT:-5432}:5432 \
            -e POSTGRES_USER=${TELEMETRY_DB_USER:-ciris} \
            -e POSTGRES_PASSWORD=${TELEMETRY_DB_PASSWORD} \
            -e POSTGRES_DB=${TELEMETRY_DB_NAME:-telemetry} \
            -v timescaledb_data:/var/lib/postgresql/data \
            timescale/timescaledb:latest-pg14
    fi

    # Wait for database to be ready
    log_info "Waiting for database to be ready..."
    for i in {1..30}; do
        if PGPASSWORD=${TELEMETRY_DB_PASSWORD} psql \
            -h localhost \
            -p ${TELEMETRY_DB_PORT:-5432} \
            -U ${TELEMETRY_DB_USER:-ciris} \
            -d ${TELEMETRY_DB_NAME:-telemetry} \
            -c "SELECT 1" &> /dev/null; then
            log_success "Database is ready"
            break
        fi

        if [ $i -eq 30 ]; then
            log_error "Database failed to start"
            exit 1
        fi

        sleep 2
    done
}

# Run migrations
run_migrations() {
    log_info "Running database migrations..."

    local migration_dir="${PROJECT_ROOT}/migrations/telemetry"

    # Check if migrations directory exists
    if [ ! -d "$migration_dir" ]; then
        log_error "Migrations directory not found: $migration_dir"
        exit 1
    fi

    # Run each migration in order
    for migration in $(ls "$migration_dir"/*.sql | sort); do
        local migration_name=$(basename "$migration")
        log_info "Applying migration: $migration_name"

        PGPASSWORD=${TELEMETRY_DB_PASSWORD} psql \
            -h localhost \
            -p ${TELEMETRY_DB_PORT:-5432} \
            -U ${TELEMETRY_DB_USER:-ciris} \
            -d ${TELEMETRY_DB_NAME:-telemetry} \
            -f "$migration" \
            --single-transaction \
            --set ON_ERROR_STOP=1

        if [ $? -eq 0 ]; then
            log_success "Applied: $migration_name"
        else
            log_error "Failed to apply migration: $migration_name"
            exit 1
        fi
    done

    log_success "All migrations applied successfully"
}

# Configure CIRISManager
configure_manager() {
    log_info "Configuring CIRISManager for telemetry..."

    local config_file="/etc/ciris-manager/config.yml"
    local telemetry_config="/etc/ciris-manager/telemetry.yml"

    # Create telemetry configuration
    sudo tee "$telemetry_config" > /dev/null << EOF
telemetry:
  enabled: true
  database_url: postgresql://${TELEMETRY_DB_USER:-ciris}:${TELEMETRY_DB_PASSWORD}@localhost:${TELEMETRY_DB_PORT:-5432}/${TELEMETRY_DB_NAME:-telemetry}
  collection_interval: ${TELEMETRY_COLLECTION_INTERVAL:-60}
  retention_days: ${TELEMETRY_RETENTION_DAYS:-30}
  enable_public_api: ${TELEMETRY_PUBLIC_API:-true}
  storage:
    type: timescaledb
    pool_size: ${TELEMETRY_POOL_SIZE:-10}
    max_overflow: ${TELEMETRY_MAX_OVERFLOW:-20}
  collectors:
    docker: true
    agents: true
    deployments: true
    versions: true
EOF

    log_success "Telemetry configuration created"
}

# Install Python dependencies
install_dependencies() {
    log_info "Installing Python dependencies..."

    cd "$PROJECT_ROOT"
    pip install -e ".[telemetry]"

    log_success "Dependencies installed"
}

# Start telemetry service
start_service() {
    log_info "Starting telemetry service..."

    # Restart CIRISManager to pick up changes
    sudo systemctl restart ciris-manager

    # Wait for service to be active
    sleep 5

    if sudo systemctl is-active ciris-manager > /dev/null; then
        log_success "CIRISManager service restarted successfully"
    else
        log_error "Failed to restart CIRISManager service"
        sudo journalctl -u ciris-manager -n 50
        exit 1
    fi
}

# Verify deployment
verify_deployment() {
    log_info "Verifying telemetry deployment..."

    # Check telemetry endpoint
    local response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/telemetry/health)

    if [ "$response" = "200" ]; then
        log_success "Telemetry health check passed"
    else
        log_error "Telemetry health check failed (HTTP $response)"
        exit 1
    fi

    # Check database connection
    PGPASSWORD=${TELEMETRY_DB_PASSWORD} psql \
        -h localhost \
        -p ${TELEMETRY_DB_PORT:-5432} \
        -U ${TELEMETRY_DB_USER:-ciris} \
        -d ${TELEMETRY_DB_NAME:-telemetry} \
        -c "SELECT COUNT(*) FROM system_summaries;" &> /dev/null

    if [ $? -eq 0 ]; then
        log_success "Database connection verified"
    else
        log_error "Cannot connect to telemetry database"
        exit 1
    fi

    # Check if data is being collected
    log_info "Waiting for first telemetry collection..."
    sleep ${TELEMETRY_COLLECTION_INTERVAL:-60}

    local count=$(PGPASSWORD=${TELEMETRY_DB_PASSWORD} psql \
        -h localhost \
        -p ${TELEMETRY_DB_PORT:-5432} \
        -U ${TELEMETRY_DB_USER:-ciris} \
        -d ${TELEMETRY_DB_NAME:-telemetry} \
        -t -c "SELECT COUNT(*) FROM agent_metrics WHERE time > NOW() - INTERVAL '2 minutes';")

    if [ "$count" -gt 0 ]; then
        log_success "Telemetry collection is working (${count} metrics collected)"
    else
        log_warning "No telemetry data collected yet"
    fi
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring..."

    # Create monitoring script
    cat > /tmp/monitor-telemetry.sh << 'EOF'
#!/bin/bash
# Check telemetry health
response=$(curl -s http://localhost:8888/telemetry/health)
if [ $? -ne 0 ]; then
    echo "CRITICAL: Telemetry API is not responding"
    exit 2
fi

# Check collection status
status=$(echo "$response" | jq -r '.collection_status')
if [ "$status" != "active" ]; then
    echo "WARNING: Collection status is $status"
    exit 1
fi

echo "OK: Telemetry is healthy"
exit 0
EOF

    sudo mv /tmp/monitor-telemetry.sh /usr/local/bin/monitor-telemetry
    sudo chmod +x /usr/local/bin/monitor-telemetry

    # Add to crontab for regular monitoring
    (crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/monitor-telemetry || /usr/bin/logger -t telemetry 'Telemetry health check failed'") | crontab -

    log_success "Monitoring configured"
}

# Main deployment flow
main() {
    log_info "Starting telemetry deployment..."

    # Load environment
    load_env

    # Run deployment steps
    check_prerequisites
    deploy_database
    run_migrations
    install_dependencies
    configure_manager
    start_service
    verify_deployment
    setup_monitoring

    log_success "Telemetry deployment completed successfully!"
    log_info "Access telemetry at: http://localhost:8888/telemetry/status"
    log_info "Public API at: http://localhost:8888/telemetry/public"
}

# Handle errors
trap 'log_error "Deployment failed at line $LINENO"' ERR

# Run main function
main "$@"
