#!/bin/bash
# CIRIS Agent Permission Fix Script (Host-side)
# Fixes permissions for agent directories on the host system
# Usage: fix_agent_permissions.sh <agent_path>

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <agent_path>"
    echo "Example: $0 /opt/ciris/agents/scout-abc123"
    exit 1
fi

AGENT_PATH="$1"

if [ ! -d "$AGENT_PATH" ]; then
    echo "Error: Agent path does not exist: $AGENT_PATH"
    exit 1
fi

echo "Fixing permissions for agent: $AGENT_PATH"

# Function to ensure directory has proper permissions
fix_dir() {
    local dir=$1
    local perms=$2
    local desc=$3

    if [ -d "$dir" ]; then
        echo "  ✓ Fixing $desc: $dir"
        chmod "$perms" "$dir"
        chown -R 1000:1000 "$dir"
    else
        echo "  ⚠ Skipping missing directory: $dir"
    fi
}

# Fix permissions for each directory
fix_dir "$AGENT_PATH/data" "755" "data"
fix_dir "$AGENT_PATH/data_archive" "755" "data_archive"
fix_dir "$AGENT_PATH/logs" "755" "logs"
fix_dir "$AGENT_PATH/config" "755" "config"
fix_dir "$AGENT_PATH/audit_keys" "700" "audit_keys"
fix_dir "$AGENT_PATH/.secrets" "700" "secrets"

echo "✅ Permission fix complete for $AGENT_PATH"
