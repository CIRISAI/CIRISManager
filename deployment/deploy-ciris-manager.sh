#!/bin/bash
# Deploy CIRISManager to production

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"; }

log "Deploying CIRISManager..."

# Step 1: Ensure we're in the right directory
cd /home/ciris/CIRISAgent || {
    error "Failed to cd to /home/ciris/CIRISAgent"
    exit 1
}

# Step 2: Update repository
log "Updating repository..."
git pull origin main || warn "Failed to pull latest changes"

# Step 3: Install Python dependencies
log "Installing Python dependencies..."
apt-get update
apt-get install -y python3-pip python3-venv python3-dev

# Step 4: Create and activate virtual environment
log "Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# Step 5: Install CIRISManager in development mode
log "Installing CIRISManager..."
pip install --upgrade pip
pip install pyyaml aiofiles

# Add ciris_manager to Python path
export PYTHONPATH="/home/ciris/CIRISAgent:$PYTHONPATH"

# Create wrapper script
log "Creating ciris-manager wrapper..."
cat > /usr/local/bin/ciris-manager << 'EOF'
#!/bin/bash
cd /home/ciris/CIRISAgent
export PYTHONPATH="/home/ciris/CIRISAgent:$PYTHONPATH"
if [ -d "venv" ]; then
    source venv/bin/activate
fi
python3 -m ciris_manager.cli "$@"
EOF
chmod +x /usr/local/bin/ciris-manager

# Step 6: Create configuration
log "Creating CIRISManager configuration..."
mkdir -p /etc/ciris-manager

if [ ! -f "/etc/ciris-manager/config.yml" ]; then
    ciris-manager --generate-config --config /etc/ciris-manager/config.yml
    
    # Update compose file path
    sed -i 's|/home/ciris/CIRISAgent/deployment/docker-compose.yml|/home/ciris/CIRISAgent/deployment/docker-compose.dev-prod.yml|' /etc/ciris-manager/config.yml
    
    log "Configuration created at /etc/ciris-manager/config.yml"
else
    log "Configuration already exists"
fi

# Step 7: Install systemd service
log "Installing systemd service..."
if [ ! -f "/etc/systemd/system/ciris-manager.service" ]; then
    cp deployment/ciris-manager.service /etc/systemd/system/
    
    # Update service file to use wrapper
    sed -i 's|ExecStart=.*|ExecStart=/usr/local/bin/ciris-manager --config /etc/ciris-manager/config.yml|' /etc/systemd/system/ciris-manager.service
    
    systemctl daemon-reload
    log "Service installed"
else
    log "Service already installed"
    systemctl daemon-reload
fi

# Step 8: Start containers if not running
log "Checking container status..."
if ! docker ps --format "{{.Names}}" | grep -q "ciris-agent-datum"; then
    log "Starting containers..."
    docker-compose -f deployment/docker-compose.dev-prod.yml up -d
else
    log "Containers already running"
fi

# Step 9: Enable and start CIRISManager
log "Starting CIRISManager service..."
systemctl enable ciris-manager
systemctl restart ciris-manager

# Wait a moment for service to start
sleep 2

# Step 10: Check status
log "Checking service status..."
if systemctl is-active ciris-manager >/dev/null 2>&1; then
    echo -e "${GREEN}✓ CIRISManager is active${NC}"
    systemctl status ciris-manager --no-pager | head -10
else
    error "CIRISManager failed to start"
    journalctl -u ciris-manager -n 20 --no-pager
    exit 1
fi

# Step 11: Verify API health
log "Verifying API health..."
sleep 5
if curl -sf http://localhost:8080/v1/system/health >/dev/null; then
    echo -e "${GREEN}✓ API is healthy${NC}"
else
    warn "API health check failed - container may still be starting"
fi

log "CIRISManager deployment complete!"
echo ""
echo "Commands:"
echo "  systemctl status ciris-manager    # Check service status"
echo "  journalctl -u ciris-manager -f    # Follow service logs"
echo "  docker ps                         # Check containers"
echo ""