# CIRISManager Production Deployment Guide

This guide covers deploying CIRISManager to a production environment with proper security, authentication, and monitoring.

## Prerequisites

- Ubuntu 20.04+ or similar Linux distribution
- Python 3.11+
- Docker and Docker Compose installed
- Domain name with SSL certificate (for OAuth redirects)
- Google OAuth credentials configured for production domain

## Architecture Overview

CIRISManager acts as the orchestrator for the entire CIRIS ecosystem:

```
┌─────────────┐     ┌──────────────────────────────────┐
│   Browser   │────▶│         Nginx (80/443)           │
└─────────────┘     └────────────┬─────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐     ┌─────────────────┐     ┌─────────────────┐
│/manager/v1/*  │     │    /v1/*        │     │/api/{agent}/v1/*│
│  Port 8888    │     │  Default Agent  │     │ Dynamic Agents  │
│ CIRISManager  │     │    (Datum)      │     │  Ports 8000+    │
└───────────────┘     └─────────────────┘     └─────────────────┘
```

**Key Points:**
- CIRISManager discovers agents and configures nginx automatically
- All routing is managed dynamically - no manual nginx edits needed
- GUI at port 3000 communicates through nginx to all services

## Phase 1: Pre-Deployment Setup

### 1.1 System Requirements

```bash
# Verify Python version
python3 --version  # Must be 3.11+

# Verify Docker
docker --version
docker-compose --version

# Create system user (if not exists)
sudo useradd -r -s /bin/false ciris-manager
```

### 1.2 Directory Structure

```bash
# Create required directories
sudo mkdir -p /opt/ciris-manager
sudo mkdir -p /etc/ciris-manager
sudo mkdir -p /var/log/ciris-manager
sudo mkdir -p /opt/ciris/agents

# Set ownership
sudo chown -R ciris-manager:ciris-manager /opt/ciris-manager
sudo chown -R ciris-manager:ciris-manager /etc/ciris-manager
sudo chown -R ciris-manager:ciris-manager /var/log/ciris-manager
sudo chown -R ciris-manager:ciris-manager /opt/ciris/agents
```

## Phase 2: Configuration

### 2.1 Create Production Configuration

```bash
# Copy example configuration
sudo cp config.example.yml /etc/ciris-manager/config.yml

# Edit with production values
sudo nano /etc/ciris-manager/config.yml
```

Update the following settings:

```yaml
# Manager settings
manager:
  host: 0.0.0.0                        # Bind to all interfaces
  port: 8888                           # API port
  agents_directory: /opt/ciris/agents  # Production agent directory
  templates_directory: /opt/ciris-manager/agent_templates
  manifest_path: /opt/ciris-manager/pre-approved-templates.json

# Authentication - CRITICAL
auth:
  mode: production                     # MUST be production

# Nginx settings (if using)
nginx:
  enabled: true                        # Enable for reverse proxy
  config_dir: /etc/nginx/sites-enabled
  container_name: nginx

# Docker settings
docker:
  registry: ghcr.io/cirisai
  image: ciris-agent:latest

# Port allocation
ports:
  start: 8000
  end: 8999
  reserved: [8080, 8888, 80, 443]
```

### 2.2 Set Environment Variables

Create environment file for systemd:

```bash
sudo nano /etc/ciris-manager/environment
```

Add production secrets:

```bash
# OAuth Configuration (REQUIRED for production)
GOOGLE_CLIENT_ID=your-production-client-id
GOOGLE_CLIENT_SECRET=your-production-client-secret

# JWT Secret (REQUIRED - generate a strong random key)
MANAGER_JWT_SECRET=$(openssl rand -base64 32)

# Configuration path
CIRIS_MANAGER_CONFIG=/etc/ciris-manager/config.yml

# Optional: Override auth mode
# CIRIS_AUTH_MODE=production
```

**Security Note:** Ensure this file has restricted permissions:
```bash
sudo chmod 600 /etc/ciris-manager/environment
sudo chown ciris-manager:ciris-manager /etc/ciris-manager/environment
```

### 2.3 Configure Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to APIs & Services > Credentials
3. Create or update OAuth 2.0 Client ID
4. Add authorized redirect URI:
   ```
   https://your-domain.com/manager/v1/oauth/callback
   ```
5. Copy Client ID and Secret to environment file

## Phase 3: Installation

### 3.1 Clone Repository

```bash
cd /opt
sudo git clone https://github.com/CIRISAI/CIRISManager.git ciris-manager
cd ciris-manager
sudo git checkout v1.0.0  # Use specific release tag
```

### 3.2 Install Dependencies

```bash
# Create virtual environment
sudo python3 -m venv venv
sudo chown -R ciris-manager:ciris-manager venv

# Install as ciris-manager user
sudo -u ciris-manager venv/bin/pip install --upgrade pip
sudo -u ciris-manager venv/bin/pip install -r requirements.txt
sudo -u ciris-manager venv/bin/pip install -e .
```

### 3.3 Install Systemd Services

```bash
# Copy service files
sudo cp deployment/ciris-manager.service /etc/systemd/system/
sudo cp deployment/ciris-manager-api.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload
```

## Phase 4: Deployment

### 4.1 Start Services

```bash
# Enable services to start on boot
sudo systemctl enable ciris-manager.service
sudo systemctl enable ciris-manager-api.service

# Start services
sudo systemctl start ciris-manager.service
sudo systemctl start ciris-manager-api.service

# Check status
sudo systemctl status ciris-manager.service
sudo systemctl status ciris-manager-api.service
```

### 4.2 Verify Logs

```bash
# Check service logs
sudo journalctl -u ciris-manager -f
sudo journalctl -u ciris-manager-api -f

# Application logs
sudo tail -f /var/log/ciris-manager/manager.log
```

## Phase 5: Post-Deployment Verification

### 5.1 Health Check

From external machine:

```bash
# Test health endpoint
curl https://your-domain.com/manager/v1/health

# Expected response:
# {"status":"healthy","service":"ciris-manager"}
```

### 5.2 Authentication Test

1. Open browser to: `https://your-domain.com`
2. Click login button
3. Complete Google OAuth flow
4. Verify redirect to authenticated dashboard

### 5.3 Functional Test

Using authenticated session:

```bash
# List agents (should be empty initially)
curl -H "Authorization: Bearer $TOKEN" \
  https://your-domain.com/manager/v1/agents

# Create test agent
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"template": "echo", "name": "Test Agent"}' \
  https://your-domain.com/manager/v1/agents

# Verify agent created
curl -H "Authorization: Bearer $TOKEN" \
  https://your-domain.com/manager/v1/agents

# Delete test agent
curl -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  https://your-domain.com/manager/v1/agents/{agent_id}
```

## Phase 6: Security Hardening

### 6.1 Firewall Configuration

```bash
# Allow only necessary ports
sudo ufw allow 22/tcp     # SSH
sudo ufw allow 80/tcp     # HTTP (redirect to HTTPS)
sudo ufw allow 443/tcp    # HTTPS
sudo ufw allow 8888/tcp   # API (if not behind proxy)
sudo ufw enable
```

### 6.2 Nginx Reverse Proxy (Recommended)

**Note:** If deploying alongside CIRISAgent, add these location blocks to the existing nginx configuration instead of creating a separate site. See `deployment/INTEGRATION_NOTES.md` for details.

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # OAuth callback compatibility route (if needed)
    location /manager/oauth/callback {
        proxy_pass http://localhost:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /manager/ {
        proxy_pass http://localhost:8888/manager/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 6.3 Regular Security Tasks

- Rotate JWT secret monthly
- Review OAuth permissions quarterly
- Monitor failed authentication attempts
- Keep Docker images updated

## Monitoring & Maintenance

### Log Management

CIRISManager uses systemd journal for logging. View logs with:

```bash
# View manager service logs
sudo journalctl -u ciris-manager -f

# View API service logs
sudo journalctl -u ciris-manager-api -f

# Export logs for a specific time range
sudo journalctl -u ciris-manager --since "1 hour ago" > manager.log
```

Journal logs are automatically rotated by systemd. To configure retention:

```bash
# Edit journal configuration
sudo nano /etc/systemd/journald.conf

# Set maximum disk usage (example: 500M)
SystemMaxUse=500M

# Restart journal service
sudo systemctl restart systemd-journald
```

### Health Monitoring

Add to monitoring system:

```bash
# Endpoint to monitor
https://your-domain.com/manager/v1/health

# Expected status code: 200
# Expected response time: <500ms
```

### Backup Strategy

Regular backups of:
- `/etc/ciris-manager/` - Configuration
- `/opt/ciris/agents/` - Agent data
- Agent metadata files

## Troubleshooting

### Service Won't Start

```bash
# Check configuration
sudo -u ciris-manager /opt/ciris-manager/venv/bin/python \
  -m ciris_manager.config.settings

# Verify environment variables
sudo -u ciris-manager env | grep -E "(GOOGLE|JWT|CIRIS)"
```

### Authentication Issues

1. Verify OAuth redirect URI matches exactly
2. Check JWT secret is set correctly
3. Ensure `auth.mode: production` in config
4. Review logs for specific error messages

### Agent Creation Fails

1. Check Docker daemon is running
2. Verify agent directory permissions
3. Ensure port range is available
4. Check Docker image accessibility

## Manual Update Process

Since CIRISManager 1.0 does not include automatic updates:

```bash
# Stop services
sudo systemctl stop ciris-manager-api ciris-manager

# Pull latest code
cd /opt/ciris-manager
sudo git pull
sudo git checkout v1.0.1  # New version

# Update dependencies
sudo -u ciris-manager venv/bin/pip install -r requirements.txt
sudo -u ciris-manager venv/bin/pip install -e .

# Restart services
sudo systemctl start ciris-manager ciris-manager-api
```

For automatic updates, consider using external tools like Watchtower for container updates.

## Support

- Documentation: https://github.com/CIRISAI/CIRISManager/docs
- Issues: https://github.com/CIRISAI/CIRISManager/issues
- Security: security@ciris.ai