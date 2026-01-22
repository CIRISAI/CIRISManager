# CIRISManager: Zero to Hero Deployment Guide

Complete guide for setting up CIRISManager infrastructure from scratch using Terraform and Ansible.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Phase 1: Infrastructure Provisioning (Terraform)](#phase-1-infrastructure-provisioning-terraform)
- [Phase 2: Manager Server Setup](#phase-2-manager-server-setup)
- [Phase 3: Agent Server Setup](#phase-3-agent-server-setup)
- [Phase 4: CIRISManager Configuration](#phase-4-cirismanager-configuration)
- [Phase 5: Deploy Your First Agent](#phase-5-deploy-your-first-agent)
- [Phase 6: Verification](#phase-6-verification)
- [Ongoing Operations](#ongoing-operations)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools

```bash
# Terraform >= 1.0
terraform -version

# Ansible >= 2.10
ansible --version
ansible-galaxy collection install community.docker

# SSH key for server access
ls ~/.ssh/ciris_deploy  # or generate with: ssh-keygen -t ed25519 -f ~/.ssh/ciris_deploy
```

### Required Accounts

1. **Vultr Account** - Get API key from [Vultr API Settings](https://my.vultr.com/settings/#settingsapi)
2. **Cloudflare Account** - For DNS management (optional but recommended)
3. **Google OAuth Credentials** - For user authentication
4. **LLM API Key** - OpenAI, Together, Groq, etc.

### Domain Setup

You'll need DNS records pointing to your servers:
- `agents.yourdomain.com` → Agents server public IP
- `scoutapi.yourdomain.com` → Scout server public IP (if using)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     CIRISManager Architecture                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────────┐         ┌─────────────────────┐            │
│  │ Manager Server      │   VPC   │ Agents Server       │            │
│  │ (10.10.0.3)         │ ←─────→ │ (10.10.0.4)         │            │
│  │                     │         │                     │            │
│  │ • CIRISManager      │  TLS    │ • Agent containers  │            │
│  │   systemd service   │  2376   │ • ciris-gui         │            │
│  │ • Agent registry    │         │ • nginx (routing)   │            │
│  │                     │         │                     │            │
│  └─────────────────────┘         └─────────────────────┘            │
│         $12/mo                          $24/mo                      │
│                                                                      │
│  ┌─────────────────────┐         ┌─────────────────────┐            │
│  │ Scout1 Server       │   VPC   │ Scout2 Server       │            │
│  │ (10.10.0.5)         │ ←─────→ │ (10.10.0.6)         │            │
│  │                     │         │                     │            │
│  │ • Scout agents      │         │ • Scout agents      │            │
│  │ • nginx (API only)  │         │ • nginx (API only)  │            │
│  │                     │         │                     │            │
│  └─────────────────────┘         └─────────────────────┘            │
│         $12/mo                          $12/mo                      │
│                                                                      │
│                    Total: ~$60/mo (4 servers)                       │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Manager runs **only** the CIRISManager service (no nginx, no agents)
- Agents server runs nginx + containers, proxies `/manager/v1/*` to manager via VPC
- All inter-server communication uses VPC IPs (10.10.0.0/24)
- Docker API on agent servers secured with TLS, restricted to VPC

---

## Phase 1: Infrastructure Provisioning (Terraform)

### 1.1 Configure Terraform Variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
# Vultr API key (get from https://my.vultr.com/settings/#settingsapi)
vultr_api_key = "your-vultr-api-key"

# SSH key ID (find with: curl -H "Authorization: Bearer $VULTR_API_KEY" https://api.vultr.com/v2/ssh-keys)
ssh_key_ids = ["your-ssh-key-id"]

# Region (ewr = New Jersey, lax = Los Angeles, etc.)
region = "ewr"

# Environment tag
environment = "test"  # or "production"

# VPC configuration
vpc_subnet = "10.10.0.0"
vpc_subnet_size = 24
```

### 1.2 Provision Infrastructure

```bash
# Initialize Terraform
terraform init

# Preview what will be created
terraform plan

# Create the infrastructure (takes ~5 minutes)
terraform apply
```

### 1.3 Save Terraform Outputs

After `terraform apply`, save the outputs:

```bash
# Get all outputs
terraform output

# Save SSH config to file
terraform output -raw ssh_config >> ~/.ssh/config

# View the IPs
terraform output manager_public_ip
terraform output agents_public_ip
terraform output agents_vpc_ip
```

Example output:
```
manager_public_ip = "45.76.226.222"
manager_vpc_ip = "10.10.0.3"
agents_public_ip = "45.76.231.182"
agents_vpc_ip = "10.10.0.4"
```

### 1.4 Update DNS

Point your domains to the server IPs:

| Domain | Record | Value |
|--------|--------|-------|
| `agents.yourdomain.com` | A | `<agents_public_ip>` |
| `scoutapi.yourdomain.com` | A | `<scout1_public_ip>` |

If using Cloudflare, enable "Proxied" for DDoS protection (orange cloud).

---

## Phase 2: Manager Server Setup

### 2.1 SSH to Manager Server

```bash
ssh ciris-manager  # Uses SSH config from Terraform output
# Or directly:
ssh -i ~/.ssh/ciris_deploy root@<manager_public_ip>
```

### 2.2 Clone CIRISManager

```bash
# Clone repository
git clone https://github.com/CIRISAI/CIRISManager.git /opt/ciris-manager
cd /opt/ciris-manager

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install CIRISManager
pip install -e .
```

### 2.3 Create Configuration Directory

```bash
mkdir -p /etc/ciris-manager/docker-certs
mkdir -p /opt/ciris/agents
```

### 2.4 Create Manager Configuration

```bash
cat > /etc/ciris-manager/config.yml << 'EOF'
# CIRISManager Configuration
api:
  host: "0.0.0.0"
  port: 8888

manager:
  agent_directory: "/opt/ciris/agents"

# OAuth configuration
oauth:
  google:
    client_id: "${GOOGLE_CLIENT_ID}"
    client_secret: "${GOOGLE_CLIENT_SECRET}"
  allowed_domains:
    - "yourdomain.com"  # Restrict to your domain

# Server definitions (will be updated after agent server setup)
servers:
  - server_id: main
    hostname: agents.yourdomain.com
    is_local: false
    vpc_ip: 10.10.0.4
    docker_host: "tcp://10.10.0.4:2376"
    tls_ca: /etc/ciris-manager/docker-certs/agents/ca.pem
    tls_cert: /etc/ciris-manager/docker-certs/agents/client-cert.pem
    tls_key: /etc/ciris-manager/docker-certs/agents/client-key.pem
EOF
```

### 2.5 Create Systemd Service

```bash
cat > /etc/systemd/system/ciris-manager.service << 'EOF'
[Unit]
Description=CIRISManager - Agent Lifecycle Manager
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ciris-manager
Environment="PATH=/opt/ciris-manager/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="GOOGLE_CLIENT_ID=your-google-client-id"
Environment="GOOGLE_CLIENT_SECRET=your-google-client-secret"
Environment="MANAGER_JWT_SECRET=your-random-32-char-secret"
Environment="CIRIS_ENCRYPTION_SALT=your-random-encryption-salt"
ExecStart=/opt/ciris-manager/venv/bin/ciris-manager --config /etc/ciris-manager/config.yml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

**Important:** Replace the placeholder values with real secrets:
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`: From Google Cloud Console
- `MANAGER_JWT_SECRET`: Generate with `openssl rand -hex 32`
- `CIRIS_ENCRYPTION_SALT`: Generate with `openssl rand -hex 16`

### 2.6 Enable Service (Don't Start Yet)

```bash
systemctl daemon-reload
systemctl enable ciris-manager
# Don't start yet - need to set up agent server first
```

---

## Phase 3: Agent Server Setup

### 3.1 Run Setup Script

From your **local machine** (not manager server):

```bash
cd /path/to/CIRISManager

# Set up the agents server
./scripts/setup_remote.sh agents.yourdomain.com 10.10.0.4 <agents_public_ip>
```

This script:
1. Installs Docker with TLS
2. Creates ciris user (uid 1000)
3. Sets up directory structure
4. Generates TLS certificates
5. Configures firewall (Docker API restricted to VPC)
6. Obtains Let's Encrypt SSL certificate
7. Deploys nginx container

### 3.2 Copy TLS Certificates to Manager

After the setup script completes, it downloads client certificates to `./docker-certs-agents.yourdomain.com/`.

Copy these to the manager server:

```bash
# From local machine
scp -r docker-certs-agents.yourdomain.com/* \
    root@<manager_public_ip>:/etc/ciris-manager/docker-certs/agents/

# On manager server, set permissions
ssh ciris-manager "chmod 400 /etc/ciris-manager/docker-certs/agents/*.pem"
```

### 3.3 Repeat for Scout Servers (Optional)

If you have scout1/scout2 servers:

```bash
# Scout1
./scripts/setup_remote.sh scoutapi.yourdomain.com 10.10.0.5 <scout1_public_ip>
scp -r docker-certs-scoutapi.yourdomain.com/* \
    root@<manager_public_ip>:/etc/ciris-manager/docker-certs/scout1/

# Scout2
./scripts/setup_remote.sh scoutapi.yourdomain.com 10.10.0.6 <scout2_public_ip>
scp -r docker-certs-scoutapi.yourdomain.com/* \
    root@<manager_public_ip>:/etc/ciris-manager/docker-certs/scout2/
```

### 3.4 Update Manager Configuration

Update `/etc/ciris-manager/config.yml` on the manager server to include all servers:

```yaml
servers:
  - server_id: main
    hostname: agents.yourdomain.com
    is_local: false
    vpc_ip: 10.10.0.4
    docker_host: "tcp://10.10.0.4:2376"
    tls_ca: /etc/ciris-manager/docker-certs/agents/ca.pem
    tls_cert: /etc/ciris-manager/docker-certs/agents/client-cert.pem
    tls_key: /etc/ciris-manager/docker-certs/agents/client-key.pem

  - server_id: scout1
    hostname: scoutapi.yourdomain.com
    is_local: false
    vpc_ip: 10.10.0.5
    docker_host: "tcp://10.10.0.5:2376"
    tls_ca: /etc/ciris-manager/docker-certs/scout1/ca.pem
    tls_cert: /etc/ciris-manager/docker-certs/scout1/client-cert.pem
    tls_key: /etc/ciris-manager/docker-certs/scout1/client-key.pem

  - server_id: scout2
    hostname: scoutapi.yourdomain.com
    is_local: false
    vpc_ip: 10.10.0.6
    docker_host: "tcp://10.10.0.6:2376"
    tls_ca: /etc/ciris-manager/docker-certs/scout2/ca.pem
    tls_cert: /etc/ciris-manager/docker-certs/scout2/client-cert.pem
    tls_key: /etc/ciris-manager/docker-certs/scout2/client-key.pem
```

---

## Phase 4: CIRISManager Configuration

### 4.1 Start CIRISManager Service

```bash
ssh ciris-manager "systemctl start ciris-manager"
```

### 4.2 Verify Service is Running

```bash
ssh ciris-manager "systemctl status ciris-manager"
ssh ciris-manager "journalctl -u ciris-manager -n 50"
```

Look for:
```
✅ Docker connection successful: main
✅ Docker connection successful: scout1
✅ Docker connection successful: scout2
```

### 4.3 Test API (via VPC)

From the agents server:

```bash
ssh ciris-agents "curl http://10.10.0.3:8888/manager/v1/health"
```

Expected: `{"status": "healthy"}`

### 4.4 Configure Nginx Proxy on Agents Server

The agents server nginx needs to proxy `/manager/v1/*` to the manager. This is handled automatically by CIRISManager when it deploys nginx configs.

---

## Phase 5: Deploy Your First Agent

### 5.1 Install CLI Client (Local Machine)

```bash
# Clone if not already
git clone https://github.com/CIRISAI/CIRISManager.git
cd CIRISManager

# Install in virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Verify CLI is available
ciris-manager-client --help
```

### 5.2 Authenticate

```bash
# Login via OAuth
ciris-manager-client auth login

# Or use environment variable
export CIRIS_MANAGER_TOKEN="your-jwt-token"
export CIRIS_MANAGER_API_URL="https://agents.yourdomain.com"
```

### 5.3 Create Your First Agent

```bash
# Create an agent on the main server
ciris-manager-client agent create \
  --name my-first-agent \
  --template basic \
  --server main \
  --env OPENAI_API_KEY=sk-your-key \
  --env OPENAI_MODEL_NAME=gpt-4o
```

### 5.4 Verify Agent is Running

```bash
# List agents
ciris-manager-client agent list

# Check agent health
ciris-manager-client inspect agent my-first-agent-xxxxx

# View logs
ciris-manager-client agent logs my-first-agent-xxxxx --lines 50
```

### 5.5 Get Agent Access Details

```bash
ciris-manager-client agent access my-first-agent-xxxxx
```

Output:
```
Agent: my-first-agent-xxxxx
Registry Key: my-first-agent-xxxxx-default-main
Server: main
Port: 8001

API Endpoint: https://agents.yourdomain.com/api/my-first-agent-xxxxx/v1/

Service Token: <token-for-api-calls>

Database:
  Type: SQLite
  Host Path: /opt/ciris/agents/my-first-agent-xxxxx/data/ciris_engine.db
```

---

## Phase 6: Verification

### 6.1 Full System Check

```bash
# Check manager health
ciris-manager-client system health

# Check all servers
ciris-manager-client server list

# Check all agents
ciris-manager-client agent list
```

### 6.2 Test Agent API

```bash
# Get service token
TOKEN=$(ciris-manager-client agent access my-first-agent-xxxxx --format json | jq -r '.service_token')

# Call agent API
curl -H "Authorization: Bearer $TOKEN" \
  https://agents.yourdomain.com/api/my-first-agent-xxxxx/v1/agent/status
```

### 6.3 Check Nginx Routes

```bash
# On agents server
ssh ciris-agents "docker exec ciris-nginx cat /etc/nginx/nginx.conf | grep -A5 'location.*my-first-agent'"
```

---

## Ongoing Operations

### Deploy Updates

```bash
# Check for staged deployments
ciris-manager-client deployment status

# Start a deployment
ciris-manager-client deployment start <deployment-id>

# Watch progress
ciris-manager-client deployment watch <deployment-id>
```

### Manage Adapters

```bash
# Load an adapter on an agent
ciris-manager-client adapter load my-first-agent-xxxxx ciris_covenant_metrics

# List adapters
ciris-manager-client adapter list my-first-agent-xxxxx
```

### Backup Configuration

```bash
# Export all agent configs
ciris-manager-client config backup --output backup-$(date +%Y%m%d).json
```

### View Logs

```bash
# Manager logs
ssh ciris-manager "journalctl -u ciris-manager -f"

# Agent logs
ciris-manager-client agent logs my-first-agent-xxxxx --follow

# Nginx logs
ssh ciris-agents "docker logs ciris-nginx --tail 100"
```

---

## Troubleshooting

### Manager Won't Start

```bash
# Check logs
ssh ciris-manager "journalctl -u ciris-manager -n 100"

# Common issues:
# - Missing environment variables (JWT_SECRET, etc.)
# - Docker cert permissions (should be 400)
# - Config syntax error
```

### Docker API Connection Failed

```bash
# Test from manager server
ssh ciris-manager "docker --tlsverify \
  --tlscacert=/etc/ciris-manager/docker-certs/agents/ca.pem \
  --tlscert=/etc/ciris-manager/docker-certs/agents/client-cert.pem \
  --tlskey=/etc/ciris-manager/docker-certs/agents/client-key.pem \
  -H tcp://10.10.0.4:2376 ps"

# If connection refused:
# - Check firewall on agents server: ufw status
# - Verify Docker is listening: ssh ciris-agents "ss -tlnp | grep 2376"
# - Check Docker daemon logs: ssh ciris-agents "journalctl -u docker -n 50"
```

### SSL Certificate Issues

```bash
# Check certificate on agents server
ssh ciris-agents "certbot certificates"

# Renew if needed
ssh ciris-agents "certbot renew"

# Reload nginx after renewal
ssh ciris-agents "docker exec ciris-nginx nginx -s reload"
```

### Agent Won't Start

```bash
# Check container logs
ssh ciris-agents "docker logs ciris-my-first-agent-xxxxx"

# Check permissions
ssh ciris-agents "ls -la /opt/ciris/agents/my-first-agent-xxxxx/"

# Fix permissions if needed
ssh ciris-agents "/home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/my-first-agent-xxxxx"
```

### Nginx Not Routing

```bash
# Verify nginx config includes agent
ssh ciris-agents "docker exec ciris-nginx cat /etc/nginx/nginx.conf | grep my-first-agent"

# Test nginx config
ssh ciris-agents "docker exec ciris-nginx nginx -t"

# Force nginx reload
ssh ciris-agents "docker exec ciris-nginx nginx -s reload"

# Or restart CIRISManager to regenerate config
ssh ciris-manager "systemctl restart ciris-manager"
```

---

## Quick Reference

### Key Paths

| Server | Path | Purpose |
|--------|------|---------|
| Manager | `/opt/ciris-manager/` | CIRISManager installation |
| Manager | `/etc/ciris-manager/config.yml` | Configuration |
| Manager | `/etc/ciris-manager/docker-certs/` | TLS certs for remote Docker |
| Manager | `/opt/ciris/agents/metadata.json` | Agent registry |
| Agents | `/opt/ciris/agents/` | Agent data directories |
| Agents | `/opt/ciris/nginx/` | Nginx config |
| Agents | `/home/ciris/shared/` | Shared scripts |

### Key Commands

```bash
# Manager operations
systemctl status ciris-manager
systemctl restart ciris-manager
journalctl -u ciris-manager -f

# Client operations
ciris-manager-client agent list
ciris-manager-client agent create --name X --template Y --server Z
ciris-manager-client deployment status
ciris-manager-client agent access <agent-id>

# Docker operations (on agent servers)
docker ps --filter 'name=ciris'
docker logs ciris-<agent-id>
docker exec ciris-nginx nginx -t
```

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `GOOGLE_CLIENT_ID` | OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret |
| `MANAGER_JWT_SECRET` | JWT signing key |
| `CIRIS_ENCRYPTION_SALT` | Token encryption salt |
| `CIRIS_MANAGER_API_URL` | CLI API endpoint |
| `CIRIS_MANAGER_TOKEN` | CLI auth token |

---

## Next Steps

1. **Set up monitoring** - Configure alerts for service health
2. **Enable CI/CD** - Set up GitHub Actions for automated deployments
3. **Add more agents** - Scale horizontally as needed
4. **Configure backups** - Regular config and data backups
5. **Review security** - Rotate secrets periodically
