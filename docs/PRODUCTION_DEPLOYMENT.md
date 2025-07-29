# Production Deployment Guide

Deploy CIRISManager to manage CIRIS agents in production environments.

## Requirements

- Ubuntu 22.04+ or compatible Linux distribution
- Python 3.11+
- Docker and docker-compose
- SSL certificates (Let's Encrypt recommended)
- Google OAuth credentials

## Quick Deploy

```bash
# Run deployment script
curl -sSL https://raw.githubusercontent.com/CIRISAI/CIRISManager/main/deployment/deploy-production.sh | \
  bash -s -- --domain your-domain.com --email admin@your-domain.com
```

## Manual Installation

### 1. System Setup

```bash
# Create ciris group and users
groupadd ciris
useradd -r -s /bin/false -d /nonexistent -c "CIRIS Manager Service" ciris-manager
useradd -r -s /bin/false -d /home/ciris -c "CIRIS Agent Service" ciris
usermod -aG docker ciris-manager
usermod -aG ciris ciris-manager
usermod -aG ciris ciris

# Create directories
mkdir -p /opt/ciris-manager
mkdir -p /etc/ciris-manager
mkdir -p /opt/ciris/agents
mkdir -p /home/ciris/nginx
mkdir -p /var/log/ciris-manager

# Set permissions
chown -R ciris-manager:ciris-manager /opt/ciris-manager
chown -R ciris-manager:ciris-manager /etc/ciris-manager
chown -R ciris-manager:ciris /opt/ciris/agents
chown -R ciris-manager:ciris /home/ciris/nginx
chmod 775 /opt/ciris/agents /home/ciris/nginx
chmod 755 /home/ciris
```

### 2. Install CIRISManager

```bash
# Clone repository
cd /opt
git clone https://github.com/CIRISAI/CIRISManager.git ciris-manager
cd ciris-manager

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### 3. Configure

Create `/etc/ciris-manager/config.yml`:

```yaml
# Manager configuration
manager:
  host: 0.0.0.0
  port: 8888
  agents_directory: /opt/ciris/agents
  templates_directory: /opt/ciris-manager/agent_templates
  manifest_path: /opt/ciris-manager/pre-approved-templates.json

# Authentication
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
  update_check_interval: 3600
  auto_pull_images: false
  restart_on_update: false

# Port allocation
ports:
  start: 8000
  end: 8999
  reserved: [8080, 8888, 80, 443, 3000]

# API configuration
api:
  prefix: /manager/v1
  cors_origins:
    - https://your-domain.com

# Nginx configuration
nginx:
  enabled: true
  config_dir: /home/ciris/nginx
  container_name: ciris-nginx
  ssl_cert_path: /etc/letsencrypt/live/your-domain.com/fullchain.pem
  ssl_key_path: /etc/letsencrypt/live/your-domain.com/privkey.pem

# Logging
logging:
  level: INFO
  format: json
```

### 4. OAuth Setup

Create `/etc/ciris-manager/environment`:

```bash
# Google OAuth
GOOGLE_CLIENT_ID=your-client-id-here
GOOGLE_CLIENT_SECRET=your-client-secret-here

# JWT Secret (generate with: openssl rand -base64 32)
MANAGER_JWT_SECRET=your-random-secret-here

# Optional: Default agent credentials
OPENAI_API_KEY=your-openai-key
DISCORD_TOKEN=your-discord-token
```

Set permissions:
```bash
chmod 600 /etc/ciris-manager/environment
chown ciris-manager:ciris-manager /etc/ciris-manager/environment
```

### 5. Systemd Service

Create `/etc/systemd/system/ciris-manager-api.service`:

```ini
[Unit]
Description=CIRIS Manager API Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ciris-manager
Group=ciris
WorkingDirectory=/opt/ciris-manager
EnvironmentFile=/etc/ciris-manager/environment
Environment="PYTHONUNBUFFERED=1"
ExecStart=/opt/ciris-manager/venv/bin/ciris-manager --config /etc/ciris-manager/config.yml
Restart=always
RestartSec=5

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=false
ReadWritePaths=/opt/ciris/agents /var/log/ciris-manager /etc/ciris-manager /var/lib/ciris-manager /home/ciris/nginx

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
systemctl daemon-reload
systemctl enable ciris-manager-api
systemctl start ciris-manager-api
```

### 6. Nginx Container

The nginx container is managed via docker-compose. CIRISManager will:
1. Generate nginx.conf automatically
2. Write to `/home/ciris/nginx/nginx.conf`
3. Start container via docker-compose
4. Reload on configuration changes

Ensure docker-compose includes:
```yaml
nginx:
  image: nginx:alpine
  container_name: ciris-nginx
  network_mode: host
  restart: unless-stopped
  volumes:
    - /home/ciris/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - /etc/letsencrypt:/etc/letsencrypt:ro
```

### 7. SSL Certificates

```bash
# Install certbot
apt-get install certbot

# Generate certificates
certbot certonly --standalone -d your-domain.com -m admin@your-domain.com --agree-tos
```

## Verification

```bash
# Check service status
systemctl status ciris-manager-api

# Test health endpoint
curl https://your-domain.com/manager/v1/health

# View logs
journalctl -u ciris-manager-api -f

# Check nginx config
cat /home/ciris/nginx/nginx.conf

# Verify containers
docker ps
```

## Updates

```bash
cd /opt/ciris-manager
git pull origin main
systemctl restart ciris-manager-api
```

## Monitoring

- Service logs: `journalctl -u ciris-manager-api`
- Container logs: `docker logs ciris-nginx`
- Agent discovery: `curl https://your-domain.com/manager/v1/agents`
- Nginx status: `docker exec ciris-nginx nginx -t`

## Backup

Regular backups should include:
- `/etc/ciris-manager/` - Configuration
- `/opt/ciris/agents/metadata.json` - Agent registry
- `/home/ciris/CIRISAgent/.env*` - Agent environment files

## Security Checklist

- [ ] OAuth credentials configured
- [ ] JWT secret generated and secured
- [ ] File permissions verified (600 for secrets)
- [ ] Systemd hardening enabled
- [ ] SSL certificates valid
- [ ] Firewall rules configured
- [ ] Docker socket permissions restricted