#!/bin/bash
# Deploy CIRISManager from Git repository
# This script clones/updates the repository and installs the manager

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"; }

# Configuration
INSTALL_DIR="${CIRIS_MANAGER_DIR:-/opt/ciris-manager}"
REPO_URL="${CIRIS_MANAGER_REPO:-https://github.com/CIRISAI/ciris-manager.git}"
BRANCH="${CIRIS_MANAGER_BRANCH:-main}"
CONFIG_DIR="/etc/ciris-manager"
VENV_DIR="$INSTALL_DIR/venv"

log "Deploying CIRISManager..."
log "Installation directory: $INSTALL_DIR"
log "Repository: $REPO_URL"
log "Branch: $BRANCH"

# Step 1: Ensure dependencies are installed
log "Installing system dependencies..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    apt-get install -y python3-pip python3-venv python3-dev git curl
elif command -v yum >/dev/null 2>&1; then
    yum install -y python3-pip python3-devel git curl
else
    error "Unsupported package manager. Please install Python 3, pip, venv, and git manually."
    exit 1
fi

# Step 2: Clone or update repository
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing repository..."
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    log "Cloning repository..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Step 3: Create/update virtual environment
log "Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Step 4: Install/upgrade Python dependencies
log "Installing Python dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .

# Step 5: Create configuration directory
log "Setting up configuration..."
mkdir -p "$CONFIG_DIR"

# Generate default config if it doesn't exist
if [ ! -f "$CONFIG_DIR/config.yml" ]; then
    log "Generating default configuration..."
    ciris-manager --generate-config --config "$CONFIG_DIR/config.yml"
    
    # Update compose file path if needed
    if [ -n "$DOCKER_COMPOSE_FILE" ]; then
        sed -i "s|compose_file:.*|compose_file: $DOCKER_COMPOSE_FILE|" "$CONFIG_DIR/config.yml"
    fi
    
    log "Configuration created at $CONFIG_DIR/config.yml"
    log "Please review and update the configuration as needed"
else
    log "Configuration already exists at $CONFIG_DIR/config.yml"
fi

# Step 6: Create systemd service
log "Installing systemd service..."
cat > /etc/systemd/system/ciris-manager.service << EOF
[Unit]
Description=CIRIS Manager Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$VENV_DIR/bin/python -m ciris_manager.cli --config $CONFIG_DIR/config.yml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Step 7: Create API-only service (optional)
log "Installing API-only service..."
cat > /etc/systemd/system/ciris-manager-api.service << EOF
[Unit]
Description=CIRIS Manager API Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
Environment="CIRIS_MANAGER_CONFIG=$CONFIG_DIR/config.yml"
ExecStart=$VENV_DIR/bin/python deployment/run-ciris-manager-api.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Step 8: Reload systemd
systemctl daemon-reload

# Step 9: Create update script
log "Creating update script..."
cat > /usr/local/bin/ciris-manager-update << EOF
#!/bin/bash
# Update CIRISManager from Git

cd $INSTALL_DIR
source $VENV_DIR/bin/activate

echo "Updating CIRISManager..."
git pull origin $BRANCH
pip install --upgrade -r requirements.txt
pip install -e .

echo "Restarting services..."
systemctl restart ciris-manager || true
systemctl restart ciris-manager-api || true

echo "Update complete!"
EOF
chmod +x /usr/local/bin/ciris-manager-update

# Step 10: Create convenience wrapper
log "Creating command wrapper..."
cat > /usr/local/bin/ciris-manager << EOF
#!/bin/bash
cd $INSTALL_DIR
source $VENV_DIR/bin/activate
exec python -m ciris_manager.cli "\$@"
EOF
chmod +x /usr/local/bin/ciris-manager

log "Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Review configuration: $CONFIG_DIR/config.yml"
echo "2. Start the service:"
echo "   - Full manager: systemctl start ciris-manager"
echo "   - API only: systemctl start ciris-manager-api"
echo "3. Enable on boot: systemctl enable ciris-manager"
echo ""
echo "Commands:"
echo "  ciris-manager --help              # Show CLI help"
echo "  ciris-manager-update              # Update from Git"
echo "  systemctl status ciris-manager    # Check service status"
echo "  journalctl -u ciris-manager -f    # Follow logs"
echo ""