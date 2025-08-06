# CIRISManager

Production-grade lifecycle management for CIRIS agents with automatic nginx routing, OAuth authentication, and canary deployments.

## Features

- **Automatic Agent Discovery** - Detects and manages CIRIS agent containers via Docker
- **Dynamic Nginx Routing** - Generates and maintains nginx configurations for multi-tenant agent access
- **Crash Loop Detection** - Prevents infinite restarts with configurable thresholds
- **OAuth Authentication** - Secure access with Google OAuth and JWT tokens
- **Canary Deployments** - Orchestrates staged rollouts with agent consent
- **RESTful API** - Complete management interface for agents and system operations
- **File-based Logging** - Comprehensive logging with rotation to `/var/log/ciris-manager/`

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/CIRISAI/CIRISManager.git
cd CIRISManager

# Install with development dependencies
pip install -e ".[dev]"

# Generate default configuration
ciris-manager --generate-config --config /etc/ciris-manager/config.yml

# Start the service
ciris-manager --config /etc/ciris-manager/config.yml
```

### CLI Usage

```bash
# Authenticate
ciris-manager auth login your-email@ciris.ai

# List agents
ciris-manager agent list

# Create new agent
ciris-manager agent create --name "my-agent" --template scout

# Delete agent
ciris-manager agent delete agent-id

# Check system status
ciris-manager system status
```

## Configuration

Default configuration at `/etc/ciris-manager/config.yml`:

```yaml
# Manager settings
manager:
  host: 0.0.0.0
  port: 8888
  agents_directory: /opt/ciris/agents

# Authentication
auth:
  mode: production  # Use OAuth
  jwt_algorithm: HS256
  jwt_expiry_hours: 24

# Nginx integration
nginx:
  enabled: true
  config_dir: /opt/ciris-manager/nginx
  container_name: ciris-nginx

# Container monitoring
watchdog:
  check_interval: 30
  crash_threshold: 3
  crash_window: 300
```

## Systemd Service

For production deployments, run as a systemd service:

```bash
# Check status
systemctl status ciris-manager

# View logs
journalctl -u ciris-manager -f

# Restart service
systemctl restart ciris-manager
```

Log files are written to `/var/log/ciris-manager/` with automatic rotation.

## API Endpoints

Base URL: `https://agents.ciris.ai/manager/v1`

### Agent Management
- `GET /agents` - List all discovered agents
- `GET /agents/{agent_id}` - Get agent details
- `POST /agents` - Create new agent from template
- `DELETE /agents/{agent_id}` - Remove agent

### Authentication
- `GET /oauth/login` - Start OAuth flow
- `GET /oauth/callback` - OAuth callback handler
- `GET /auth/user` - Get current user info

### System
- `GET /health` - Service health check
- `GET /templates` - List available agent templates
- `GET /env/default` - Get default environment variables

### CD Orchestration
- `POST /updates/notify` - Receive deployment notification (requires DEPLOY_TOKEN)
- `GET /updates/status` - Check deployment status (requires DEPLOY_TOKEN)

## Architecture

### Nginx Routing

CIRISManager generates complete nginx configurations automatically:

**Route Structure:**
- `/` - Manager GUI (static files)
- `/agent/{agent_id}` - Agent GUI (multi-tenant)
- `/manager/v1/*` - Manager API
- `/api/{agent_id}/*` - Agent APIs (no `/v1/` prefix needed)

**Key Implementation Details:**
- Configuration written in-place to preserve Docker bind mount inode
- No default routes - explicit agent specification required
- WebSocket support for all agent connections
- SSL/TLS termination at nginx level

### Multi-Tenant Agent Access

Agents are accessed through the gateway with automatic path translation:
- Client calls: `/api/{agent_id}/agent/interact`
- Nginx forwards to: `http://agent_{agent_id}/v1/agent/interact`
- SDK handles prefix stripping automatically in managed mode

## Docker Integration

Agents are discovered through:
- Docker container labels
- Running state monitoring
- Port allocation tracking

Requirements:
- Docker socket access (`/var/run/docker.sock`)
- Containers in same network or host mode
- Proper container naming conventions

## Authentication

### OAuth Setup

CIRISManager supports both OAuth web flow and device flow:

**Environment Variables** (`/etc/ciris-manager/environment`):
```bash
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-secret
MANAGER_JWT_SECRET=random-secret
```

**Google Cloud Console Setup:**
1. Enable OAuth 2.0
2. Add redirect URI: `https://your-domain/manager/v1/oauth/callback`
3. Enable device flow for CLI authentication

**CLI Authentication:**
```bash
ciris-manager auth login your-email@ciris.ai
# Follow device flow instructions
```

## Agent Management

### Creating Agents

```bash
# Using CLI
ciris-manager agent create --name "my-agent" --template scout

# Using Python SDK
from ciris_manager.sdk import CIRISManagerClient

client = CIRISManagerClient(base_url="https://agents.ciris.ai")
agent = client.create_agent(
    name="my-agent",
    template="scout",
    environment={"CUSTOM_VAR": "value"}
)
```

### Available Templates
- `scout` - Basic agent with exploration capabilities
- `echo` - Simple echo bot for testing
- `datum` - Data processing agent

Templates are defined in `/opt/ciris-manager/templates/`

## Monitoring

The watchdog service:
- Checks container health every 30 seconds
- Detects crash loops (3 crashes in 5 minutes)
- Prevents infinite restart loops
- Logs incidents for debugging

## Directory Structure

```
/opt/ciris-manager/          # Installation directory
/etc/ciris-manager/          # Configuration files
├── config.yml               # Main configuration
└── environment              # OAuth secrets

/opt/ciris-manager/nginx/    # Nginx configurations
└── agents.conf              # Generated agent routes

/opt/ciris/agents/           # Agent data
└── metadata.json            # Agent registry
```

## Troubleshooting

### Common Issues

**Nginx routes not updating:**
- Check if config is written in-place (preserves inode for bind mount)
- Verify with: `docker exec ciris-nginx cat /etc/nginx/nginx.conf | grep agent`
- Restart nginx container if needed: `docker restart ciris-nginx`

**Agent API returns 404:**
- Multi-tenant routes don't include `/v1/` prefix
- Correct: `/api/agent-id/agent/interact`
- Wrong: `/api/agent-id/v1/agent/interact`

**OAuth authentication fails:**
- Verify environment variables in `/etc/ciris-manager/environment`
- Check redirect URI matches Google Console configuration
- Ensure JWT secret is set

### Useful Commands

```bash
# Check service logs
journalctl -u ciris-manager -f

# View file-based logs
tail -f /var/log/ciris-manager/manager.log
tail -f /var/log/ciris-manager/nginx-updates.log

# Verify nginx configuration
docker exec ciris-nginx nginx -t

# Check agent health
curl https://agents.ciris.ai/api/{agent-id}/system/health
```

## Continuous Deployment

CIRISManager orchestrates canary deployments automatically:

**Deployment Phases:**
1. **Explorers** (10%) - Early adopters test new versions
2. **Early Adopters** (20%) - Expanded testing group
3. **General** (70%) - Majority rollout

**GitHub Actions Integration:**
```yaml
- name: Notify CIRISManager
  run: |
    curl -X POST https://agents.ciris.ai/manager/v1/updates/notify \
      -H "X-Deploy-Token: ${{ secrets.DEPLOY_TOKEN }}" \
      -d '{"agent_image": "ghcr.io/cirisai/ciris-agent:latest"}'
```

Agents receive update notifications and can accept, defer, or reject updates based on their current state.

## Security

- OAuth authentication required in production
- JWT tokens for API access
- Role-based permissions (OBSERVER, ADMIN, SYSTEM_ADMIN)
- Secure systemd service configuration
- Network isolation between agents
- CD endpoints protected by deployment token

## License

Apache 2.0 - See LICENSE file