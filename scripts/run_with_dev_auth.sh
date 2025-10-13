#!/bin/bash
# Safely run agent management with temporary development auth mode
set -e

CONFIG_FILE="/etc/ciris-manager/config.yml"
BACKUP_FILE="/tmp/ciris-manager-config-backup-$(date +%s).yml"

echo "====================================================================="
echo " Safe Agent Management with Temporary Development Auth"
echo "====================================================================="

# Backup current config
echo "[1/5] Backing up config to $BACKUP_FILE..."
cp "$CONFIG_FILE" "$BACKUP_FILE"

# Change auth mode to development
echo "[2/5] Temporarily setting auth mode to development..."
sed -i 's/mode: production/mode: development/' "$CONFIG_FILE"

# Restart manager to apply config
echo "[3/5] Restarting ciris-manager..."
systemctl restart ciris-manager
echo "    Waiting for manager API to be ready..."
sleep 15  # Wait longer for manager to fully start

# Run the management script with environment variables
echo "[4/5] Running agent management script..."
cd /opt/ciris-manager

# Source environment file used by systemd service
set -a  # automatically export all variables
source /etc/ciris-manager/environment
set +a

python3 manage_scout_agent.py

# Restore original config
echo "[5/5] Restoring production auth mode..."
cp "$BACKUP_FILE" "$CONFIG_FILE"
systemctl restart ciris-manager

echo "====================================================================="
echo " ✅ Complete! Auth mode restored to production."
echo "====================================================================="
