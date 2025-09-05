#!/bin/bash
# Backup script for CIRIS Manager
# Backs up configuration, agent data, and metadata

set -e

# Configuration
BACKUP_DIR="/var/backups/ciris-manager"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="ciris-backup-$TIMESTAMP"

# Directories to backup
BACKUP_PATHS=(
    "/etc/ciris-manager"           # Configuration
    "/opt/ciris/agents"            # Agent data and metadata
    "/opt/ciris-manager/agent_templates"  # Templates
)

# Optional: Remote backup destination (configure as needed)
# REMOTE_BACKUP="user@backup-server:/backups/ciris"

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "Starting CIRIS Manager backup..."
echo "Backup timestamp: $TIMESTAMP"

# Create temporary directory for this backup
TEMP_DIR="$BACKUP_DIR/$BACKUP_NAME"
mkdir -p "$TEMP_DIR"

# Function to backup a directory
backup_directory() {
    local src=$1
    local name=$(basename "$src")

    if [ -d "$src" ]; then
        echo "Backing up $src..."
        tar -czf "$TEMP_DIR/${name}.tar.gz" -C "$(dirname "$src")" "$name" 2>/dev/null || {
            echo "Warning: Some files in $src could not be backed up"
        }
    else
        echo "Warning: $src does not exist, skipping..."
    fi
}

# Backup each directory
for path in "${BACKUP_PATHS[@]}"; do
    backup_directory "$path"
done

# Export Docker container list
echo "Exporting Docker container information..."
docker ps -a --filter "label=ciris.agent" --format json > "$TEMP_DIR/docker-containers.json" 2>/dev/null || true

# Export Docker compose file if exists
if [ -f "/opt/ciris/agents/docker-compose.yml" ]; then
    cp "/opt/ciris/agents/docker-compose.yml" "$TEMP_DIR/docker-compose.yml"
fi

# Create backup metadata
cat > "$TEMP_DIR/backup-metadata.json" << EOF
{
    "timestamp": "$TIMESTAMP",
    "date": "$(date -Iseconds)",
    "hostname": "$(hostname)",
    "version": "$(ciris-manager --version 2>/dev/null || echo 'unknown')",
    "included_paths": $(printf '%s\n' "${BACKUP_PATHS[@]}" | jq -R . | jq -s .),
    "backup_size": "pending"
}
EOF

# Create single archive
echo "Creating backup archive..."
cd "$BACKUP_DIR"
tar -czf "$BACKUP_NAME.tar.gz" "$BACKUP_NAME"

# Calculate final size
BACKUP_SIZE=$(du -h "$BACKUP_NAME.tar.gz" | cut -f1)
echo "Backup size: $BACKUP_SIZE"

# Update metadata with size
jq --arg size "$BACKUP_SIZE" '.backup_size = $size' "$TEMP_DIR/backup-metadata.json" > "$TEMP_DIR/backup-metadata.json.tmp"
mv "$TEMP_DIR/backup-metadata.json.tmp" "$TEMP_DIR/backup-metadata.json"

# Clean up temporary directory
rm -rf "$TEMP_DIR"

# Optional: Copy to remote backup location
if [ ! -z "$REMOTE_BACKUP" ]; then
    echo "Copying backup to remote location..."
    scp "$BACKUP_DIR/$BACKUP_NAME.tar.gz" "$REMOTE_BACKUP/" || {
        echo "Warning: Failed to copy backup to remote location"
    }
fi

# Clean up old backups
echo "Cleaning up old backups..."
find "$BACKUP_DIR" -name "ciris-backup-*.tar.gz" -mtime +$RETENTION_DAYS -delete

# List remaining backups
echo ""
echo "Current backups:"
ls -lh "$BACKUP_DIR"/ciris-backup-*.tar.gz 2>/dev/null | tail -5

echo ""
echo "Backup completed: $BACKUP_DIR/$BACKUP_NAME.tar.gz"

# Verify backup integrity
echo "Verifying backup integrity..."
tar -tzf "$BACKUP_DIR/$BACKUP_NAME.tar.gz" > /dev/null && echo "Backup verification: OK" || {
    echo "ERROR: Backup verification failed!"
    exit 1
}
