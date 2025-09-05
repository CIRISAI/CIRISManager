#!/bin/bash
# Restore script for CIRIS Manager
# Restores configuration, agent data, and metadata from backup

set -e

# Check arguments
if [ $# -ne 1 ]; then
    echo "Usage: $0 <backup-file>"
    echo "Example: $0 /var/backups/ciris-manager/ciris-backup-20240115_120000.tar.gz"
    exit 1
fi

BACKUP_FILE=$1
RESTORE_DIR="/tmp/ciris-restore-$$"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

# Verify backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "CIRIS Manager Restore Utility"
echo "============================="
echo "Backup file: $BACKUP_FILE"
echo ""
echo "WARNING: This will restore CIRIS Manager configuration and data."
echo "Current configuration will be backed up to /tmp/ciris-pre-restore-backup"
echo ""
read -p "Continue with restore? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

# Stop services
echo "Stopping CIRIS Manager services..."
systemctl stop ciris-manager-api || true
systemctl stop ciris-manager || true

# Create pre-restore backup
echo "Creating pre-restore backup..."
PRE_RESTORE_BACKUP="/tmp/ciris-pre-restore-backup-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$PRE_RESTORE_BACKUP"

# Backup current state
for dir in /etc/ciris-manager /opt/ciris/agents; do
    if [ -d "$dir" ]; then
        cp -a "$dir" "$PRE_RESTORE_BACKUP/" || true
    fi
done

# Extract backup
echo "Extracting backup..."
mkdir -p "$RESTORE_DIR"
tar -xzf "$BACKUP_FILE" -C "$RESTORE_DIR"

# Find the backup directory (should be named ciris-backup-TIMESTAMP)
BACKUP_CONTENT=$(find "$RESTORE_DIR" -maxdepth 1 -name "ciris-backup-*" -type d | head -1)

if [ -z "$BACKUP_CONTENT" ]; then
    echo "ERROR: Invalid backup format"
    rm -rf "$RESTORE_DIR"
    exit 1
fi

# Display backup metadata
if [ -f "$BACKUP_CONTENT/backup-metadata.json" ]; then
    echo ""
    echo "Backup metadata:"
    jq . "$BACKUP_CONTENT/backup-metadata.json"
    echo ""
fi

# Restore configuration
if [ -f "$BACKUP_CONTENT/ciris-manager.tar.gz" ]; then
    echo "Restoring configuration..."
    mkdir -p /etc/ciris-manager
    tar -xzf "$BACKUP_CONTENT/ciris-manager.tar.gz" -C /etc/
    chown -R ciris-manager:ciris-manager /etc/ciris-manager
    chmod 600 /etc/ciris-manager/environment
fi

# Restore agent data
if [ -f "$BACKUP_CONTENT/agents.tar.gz" ]; then
    echo "Restoring agent data..."
    mkdir -p /opt/ciris
    tar -xzf "$BACKUP_CONTENT/agents.tar.gz" -C /opt/ciris/
    chown -R ciris-manager:ciris-manager /opt/ciris/agents
fi

# Restore templates
if [ -f "$BACKUP_CONTENT/agent_templates.tar.gz" ]; then
    echo "Restoring agent templates..."
    mkdir -p /opt/ciris-manager
    tar -xzf "$BACKUP_CONTENT/agent_templates.tar.gz" -C /opt/ciris-manager/
fi

# Restore docker-compose.yml if present
if [ -f "$BACKUP_CONTENT/docker-compose.yml" ]; then
    echo "Restoring docker-compose.yml..."
    cp "$BACKUP_CONTENT/docker-compose.yml" /opt/ciris/agents/
fi

# Verify critical files
echo "Verifying restored files..."
VERIFY_ERRORS=0

if [ ! -f "/etc/ciris-manager/config.yml" ]; then
    echo "ERROR: Configuration file not restored"
    VERIFY_ERRORS=$((VERIFY_ERRORS + 1))
fi

if [ ! -f "/etc/ciris-manager/environment" ]; then
    echo "ERROR: Environment file not restored"
    VERIFY_ERRORS=$((VERIFY_ERRORS + 1))
fi

if [ $VERIFY_ERRORS -gt 0 ]; then
    echo ""
    echo "ERROR: Restore verification failed!"
    echo "Pre-restore backup available at: $PRE_RESTORE_BACKUP"
    exit 1
fi

# Clean up
rm -rf "$RESTORE_DIR"

# Prompt to restart services
echo ""
echo "Restore completed successfully!"
echo ""
echo "Pre-restore backup saved to: $PRE_RESTORE_BACKUP"
echo ""
echo "Next steps:"
echo "1. Verify configuration in /etc/ciris-manager/config.yml"
echo "2. Update any environment-specific settings"
echo "3. Start services with:"
echo "   sudo systemctl start ciris-manager"
echo "   sudo systemctl start ciris-manager-api"
echo ""
read -p "Start services now? (yes/no): " start_services

if [ "$start_services" = "yes" ]; then
    echo "Starting services..."
    systemctl start ciris-manager
    systemctl start ciris-manager-api

    # Wait for services to start
    sleep 5

    # Check status
    echo ""
    echo "Service status:"
    systemctl is-active ciris-manager && echo "ciris-manager: active" || echo "ciris-manager: failed"
    systemctl is-active ciris-manager-api && echo "ciris-manager-api: active" || echo "ciris-manager-api: failed"
else
    echo "Services not started. Start manually when ready."
fi
