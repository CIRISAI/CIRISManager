#!/bin/bash
# CIRIS Agent Permission Init Script
# This script ensures proper permissions for agent directories when running in a container
# It should be run at container startup before the main application

set -e

echo "Initializing CIRIS agent directory permissions..."

# Function to ensure directory exists with proper permissions
ensure_dir() {
    local dir=$1
    local perms=$2
    local desc=$3

    if [ ! -d "$dir" ]; then
        echo "Creating $desc directory: $dir"
        mkdir -p "$dir"
    fi

    # Check if we can write to the directory
    if ! touch "$dir/.permission_test" 2>/dev/null; then
        echo "WARNING: Cannot write to $dir - attempting to fix permissions"
        # Try to change ownership if we have permission
        if chown -R $(id -u):$(id -g) "$dir" 2>/dev/null; then
            echo "✓ Fixed ownership for $dir"
        else
            echo "✗ Could not fix ownership for $dir (may need container to run with appropriate user mapping)"
        fi
    else
        rm -f "$dir/.permission_test"
        echo "✓ $desc directory is writable: $dir"
    fi

    # Set the correct permissions
    chmod "$perms" "$dir" 2>/dev/null || true
}

# Check and fix permissions for each required directory
ensure_dir "/app/data" "755" "Data"
ensure_dir "/app/data_archive" "755" "Data Archive"
ensure_dir "/app/logs" "755" "Logs"
ensure_dir "/app/config" "755" "Config"
ensure_dir "/app/audit_keys" "700" "Audit Keys"
ensure_dir "/app/.secrets" "700" "Secrets"

echo "Permission initialization complete. Starting CIRIS agent..."

# Execute the original command
exec "$@"
