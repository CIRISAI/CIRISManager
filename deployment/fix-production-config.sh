#!/bin/bash
# Fix production configuration to use CIRISManager as source of truth

set -e

echo "=== Fixing CIRISManager Production Configuration ==="

# Backup current config
if [ -f /etc/ciris-manager/config.yml ]; then
    sudo cp /etc/ciris-manager/config.yml /etc/ciris-manager/config.yml.backup
    echo "✓ Backed up existing config"
fi

# Create proper config from template
cat > /tmp/config.yml << 'EOF'
# Manager configuration
manager:
  host: 0.0.0.0
  port: 8888
  agents_directory: /opt/ciris/agents
  templates_directory: /opt/ciris-manager/agent_templates
  manifest_path: /opt/ciris-manager/pre-approved-templates.json
  metadata_file: /opt/ciris/agents/metadata.json
  
# Authentication configuration
auth:
  mode: production
  jwt_algorithm: HS256
  jwt_expiry_hours: 24
  
# Docker configuration
docker:
  compose_file: /opt/ciris/agents/docker-compose.yml
  registry: ghcr.io/cirisai
  image: ciris-agent:latest
  network_name: ciris-network
  
# Watchdog configuration
watchdog:
  enabled: true
  check_interval: 30
  restart_delay: 30
  crash_threshold: 3
  crash_window: 300
  
# Container management
container_management:
  enabled: true
  update_check_interval: 300
  auto_pull_images: false
  restart_on_update: false
  
# Port allocation
ports:
  start: 8000
  end: 8999
  reserved: [8080, 8888, 80, 443, 3000]
  
# API configuration
api:
  host: 0.0.0.0
  port: 8888
  reload: false
  
# Nginx configuration (if using nginx management)
nginx:
  enabled: false  # Disabled since using host nginx
  config_dir: /etc/nginx/sites-enabled
  container_name: nginx
  
# Logging configuration
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: /var/log/ciris-manager/manager.log
  max_bytes: 10485760
  backup_count: 5
EOF

# Copy to proper location
sudo cp /tmp/config.yml /etc/ciris-manager/config.yml
sudo chown ciris-manager:ciris-manager /etc/ciris-manager/config.yml
sudo chmod 644 /etc/ciris-manager/config.yml

echo "✓ Updated configuration"

# Create directories if missing
sudo mkdir -p /opt/ciris/agents
sudo mkdir -p /opt/ciris-manager/agent_templates
sudo chown -R ciris-manager:ciris-manager /opt/ciris/agents
sudo chown -R ciris-manager:ciris-manager /opt/ciris-manager

echo "✓ Verified directories"

# Restart service
sudo systemctl restart ciris-manager-api

echo "✓ Restarted service"
echo ""
echo "=== Configuration Fixed! ==="
echo "CIRISManager is now using its own templates and configuration."
echo ""
echo "Test agent creation: https://agents.ciris.ai"