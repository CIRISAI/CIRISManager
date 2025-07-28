#!/bin/bash
#
# CIRISManager Installation Script
#
# This script installs CIRISManager as a systemd service
# for automatic container management and crash detection.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
INSTALL_DIR="/home/ciris/CIRISAgent"
CONFIG_DIR="/etc/ciris-manager"
SERVICE_FILE="/etc/systemd/system/ciris-manager.service"
LOG_FILE="/var/log/ciris-manager-install.log"

# Logging function
log() {
    echo -e "$1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "${RED}ERROR: $1${NC}"
    exit 1
}

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error_exit "This script must be run as root (use sudo)"
    fi
}

# Check dependencies
check_dependencies() {
    log "${YELLOW}Checking dependencies...${NC}"
    
    # Check Python 3.8+
    if ! command -v python3 &> /dev/null; then
        error_exit "Python 3 is not installed"
    fi
    
    python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [[ $(echo "$python_version < 3.8" | bc) -eq 1 ]]; then
        error_exit "Python 3.8 or higher is required (found $python_version)"
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        error_exit "Docker is not installed"
    fi
    
    # Check docker-compose
    if ! command -v docker-compose &> /dev/null; then
        error_exit "docker-compose is not installed"
    fi
    
    # Check pip
    if ! command -v pip3 &> /dev/null; then
        error_exit "pip3 is not installed"
    fi
    
    log "${GREEN}✓ All dependencies satisfied${NC}"
}

# Install CIRISManager
install_manager() {
    log "${YELLOW}Installing CIRISManager...${NC}"
    
    # Check if directory exists
    if [[ ! -d "$INSTALL_DIR" ]]; then
        error_exit "CIRIS installation not found at $INSTALL_DIR"
    fi
    
    cd "$INSTALL_DIR"
    
    # Install package
    log "Installing Python package..."
    pip3 install -e . >> "$LOG_FILE" 2>&1 || error_exit "Failed to install Python package"
    
    # Verify installation
    if ! command -v ciris-manager &> /dev/null; then
        error_exit "CIRISManager installation failed - command not found"
    fi
    
    log "${GREEN}✓ CIRISManager installed${NC}"
}

# Create configuration
create_config() {
    log "${YELLOW}Creating configuration...${NC}"
    
    # Create config directory
    mkdir -p "$CONFIG_DIR"
    
    # Check for existing config
    if [[ -f "$CONFIG_DIR/config.yml" ]]; then
        log "${YELLOW}Configuration already exists at $CONFIG_DIR/config.yml${NC}"
        read -p "Overwrite existing configuration? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Keeping existing configuration"
            return
        fi
    fi
    
    # Determine compose file location
    if [[ -f "$INSTALL_DIR/deployment/docker-compose.production.yml" ]]; then
        COMPOSE_FILE="$INSTALL_DIR/deployment/docker-compose.production.yml"
    elif [[ -f "$INSTALL_DIR/deployment/docker-compose.yml" ]]; then
        COMPOSE_FILE="$INSTALL_DIR/deployment/docker-compose.yml"
    elif [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
        COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"
    else
        COMPOSE_FILE="$INSTALL_DIR/deployment/docker-compose.dev.yml"
    fi
    
    # Generate configuration
    cat > "$CONFIG_DIR/config.yml" << EOF
# CIRISManager Configuration
# Generated on $(date)

manager:
  port: 9999
  host: 127.0.0.1

docker:
  compose_file: $COMPOSE_FILE

watchdog:
  check_interval: 30    # Check containers every 30 seconds
  crash_threshold: 3    # Stop after 3 crashes
  crash_window: 300     # Within 5 minutes (300 seconds)

updates:
  check_interval: 300   # Check for updates every 5 minutes
  auto_notify: true     # Notify agents of available updates

container_management:
  interval: 60          # Run docker-compose up -d every 60 seconds
  pull_images: true     # Pull latest images before starting
EOF
    
    log "${GREEN}✓ Configuration created at $CONFIG_DIR/config.yml${NC}"
}

# Install systemd service
install_service() {
    log "${YELLOW}Installing systemd service...${NC}"
    
    # Check if service already exists
    if systemctl list-unit-files | grep -q ciris-manager.service; then
        log "${YELLOW}Service already exists${NC}"
        systemctl stop ciris-manager 2>/dev/null || true
    fi
    
    # Copy service file
    cp "$INSTALL_DIR/deployment/ciris-manager.service" "$SERVICE_FILE" || \
        error_exit "Failed to copy service file"
    
    # Update WorkingDirectory in service file
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|g" "$SERVICE_FILE"
    
    # Reload systemd
    systemctl daemon-reload
    
    # Enable service
    systemctl enable ciris-manager || error_exit "Failed to enable service"
    
    log "${GREEN}✓ Systemd service installed${NC}"
}

# Start service
start_service() {
    log "${YELLOW}Starting CIRISManager service...${NC}"
    
    systemctl start ciris-manager || error_exit "Failed to start service"
    
    # Wait for startup
    sleep 2
    
    # Check status
    if systemctl is-active --quiet ciris-manager; then
        log "${GREEN}✓ CIRISManager is running${NC}"
    else
        error_exit "CIRISManager failed to start - check logs with: journalctl -u ciris-manager"
    fi
}

# Show status
show_status() {
    log "\n${GREEN}Installation Complete!${NC}"
    log "\n${YELLOW}Service Status:${NC}"
    systemctl status ciris-manager --no-pager || true
    
    log "\n${YELLOW}Useful Commands:${NC}"
    log "  View logs:         sudo journalctl -u ciris-manager -f"
    log "  Check status:      sudo systemctl status ciris-manager"
    log "  Stop service:      sudo systemctl stop ciris-manager"
    log "  Start service:     sudo systemctl start ciris-manager"
    log "  Edit config:       sudo nano $CONFIG_DIR/config.yml"
    log "  Restart service:   sudo systemctl restart ciris-manager"
}

# Main installation flow
main() {
    log "${GREEN}CIRISManager Installation Script${NC}"
    log "================================"
    log "Log file: $LOG_FILE"
    echo
    
    check_root
    check_dependencies
    install_manager
    create_config
    install_service
    start_service
    show_status
}

# Run main
main "$@"