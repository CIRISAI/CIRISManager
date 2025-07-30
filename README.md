# CIRISManager

Production-grade lifecycle management for CIRIS agents with automatic nginx configuration.

## What It Does

CIRISManager runs as a systemd service that:
- Discovers and monitors CIRIS agent containers
- Generates nginx configurations automatically
- Detects crash loops and prevents infinite restarts
- Provides REST API for agent management
- Handles OAuth authentication for secure access

## Installation

```bash
# Production deployment
cd /opt
git clone https://github.com/CIRISAI/CIRISManager.git ciris-manager
cd ciris-manager
./deployment/deploy-production.sh --domain agents.ciris.ai --email admin@ciris.ai
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

## Running

The service runs automatically via systemd:

```bash
# Check status
systemctl status ciris-manager-api

# View logs
journalctl -u ciris-manager-api -f

# Restart after config changes
systemctl restart ciris-manager-api
```

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

## Nginx Management

CIRISManager automatically generates nginx configurations when agents change:

1. Discovers agents via Docker labels
2. Generates dynamic agent routes only (agents.conf)
3. Writes to `/opt/ciris-manager/nginx/agents.conf`
4. Reloads nginx container

The generated config includes:
- Dynamic agent upstreams and routes
- Default /v1 route pointing to primary agent
- WebSocket support for all agents
- Automatic route updates when agents change

Note: Static infrastructure (SSL, GUI routes) is managed by the nginx template in CIRISAgent

## Docker Integration

Agents are discovered through:
- Docker container labels
- Running state monitoring
- Port allocation tracking

Requirements:
- Docker socket access (`/var/run/docker.sock`)
- Containers in same network or host mode
- Proper container naming conventions

## OAuth Setup

Production deployments use Google OAuth:

1. Set environment variables in `/etc/ciris-manager/environment`:
   ```
   GOOGLE_CLIENT_ID=your-client-id
   GOOGLE_CLIENT_SECRET=your-secret
   MANAGER_JWT_SECRET=random-secret
   ```

2. Configure OAuth consent screen in Google Cloud Console

3. Add redirect URI: `https://agents.ciris.ai/manager/oauth/callback`

## Creating Agents

Agents are created from templates:

```bash
# Via API
curl -X POST https://agents.ciris.ai/manager/v1/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "echo",
    "name": "echo-bot",
    "environment": {
      "DISCORD_TOKEN": "your-token"
    }
  }'
```

Templates define:
- Base container image
- Required environment variables
- Port allocations
- Resource limits

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

Check service logs:
```bash
# Manager logs
journalctl -u ciris-manager-api -f

# Container logs
docker logs ciris-nginx
docker logs ciris-agent-datum

# Nginx config
cat /opt/ciris-manager/nginx/agents.conf
```

Common issues:
- **OAuth not working**: Check environment variables in `/etc/ciris-manager/environment`
- **Nginx not updating**: Ensure service has write access to `/opt/ciris-manager/nginx`
- **Agents not discovered**: Verify Docker socket permissions

## Security

- OAuth authentication required in production
- JWT tokens for API access
- Role-based permissions (OBSERVER, ADMIN, SYSTEM_ADMIN)
- Secure systemd service configuration
- Network isolation between agents

## License

Apache 2.0 - See LICENSE file