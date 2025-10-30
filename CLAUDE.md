# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Development Principles

### Simplicity First
- **One file is better than two with includes** - We generate one complete nginx.conf
- **Explicit is better than implicit** - No default routes, every API call specifies the agent
- **Boring is better than clever** - Choose solutions that will work in 5 years
- **Static is better than dynamic** - Manager GUI uses static HTML/JS, not another container

### Clear Ownership
- **CIRISManager owns infrastructure** - Nginx, routing, monitoring
- **CIRISAgent owns applications** - Agents, GUI, business logic
- **No mixed concerns** - Each repo has a clear, single purpose

### Why These Matter
Every architectural decision should reduce complexity, not add it. If you can't explain a feature in one sentence, it's too complex. See `docs/NGINX_ARCHITECTURE_LESSONS.md` for detailed examples.

### **CRITICAL: Always Use ciris-manager-client**
**ALL agent operations MUST go through `ciris-manager-client`**. This is non-negotiable.

- **NEVER use docker commands directly** (no `docker restart`, `docker-compose up`, etc.)
- **NEVER use curl/httpx to call manager API directly**
- **NEVER use SSH to manually manipulate containers**

**If ciris-manager-client doesn't support an operation you need:**
1. Add the feature to the SDK (`ciris_manager_sdk/`)
2. Add the command to the client (`ciris_manager_client/commands/`)
3. Then use it

**This ensures:**
- All operations are audited
- Deployment orchestration is respected
- State remains consistent
- We have a single source of truth for operations

**Examples of CORRECT usage:**
```bash
# Deploy agent
ciris-manager-client agent deploy datum --version 1.5.1 --strategy docker

# List agents
ciris-manager-client agent list

# Check deployment status
ciris-manager-client deployment status
```

**Examples of INCORRECT usage:**
```bash
# ❌ WRONG - bypasses manager
docker restart ciris-datum

# ❌ WRONG - bypasses client
curl http://localhost:8888/manager/v1/agents

# ❌ WRONG - manual container manipulation
cd /opt/ciris/agents/datum && docker-compose up -d
```

## Essential Commands

### Development Setup
```bash
# Install in development mode with all dependencies
pip install -e ".[dev]"

# Install production dependencies only
pip install -r requirements.txt
```

### Running the Service
```bash
# Full service with container management and watchdog
ciris-manager --config /etc/ciris-manager/config.yml

# Generate default configuration
ciris-manager --generate-config --config /etc/ciris-manager/config.yml
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test module
pytest tests/ciris_manager/test_manager.py

# Run tests with coverage
pytest --cov=ciris_manager tests/
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev      # Start development server
npm run build    # Build for production
npm run lint     # Run linter
npm run type-check  # Run TypeScript type checking
```

### Code Quality
```bash
# Format code with ruff
ruff format ciris_manager/ tests/

# Run linter
ruff check ciris_manager/ tests/

# Type checking
mypy ciris_manager/
```

### CLI Client Tool

The **CIRISManager CLI client** is a comprehensive command-line tool for managing agents and infrastructure. It is separate from the manager service itself.

**Location:** `ciris_manager_client/` directory (not `ciris_manager/`)

**Entry Point:** `ciris-manager-client` command (installed via pip)

**Authentication:**
- Token stored in `~/.manager_token` file
- Or set `CIRIS_MANAGER_TOKEN` environment variable
- Points to production API by default: `https://agents.ciris.ai`

**Available Commands:**

1. **Agent Management** (`ciris-manager-client agent <command>`)
   ```bash
   # List all agents with status and versions
   ciris-manager-client agent list

   # Get detailed agent information (JSON)
   ciris-manager-client agent get <agent-id>

   # Create a new agent
   ciris-manager-client agent create --name myagent --template basic --server scout

   # Start/Stop/Restart agent
   ciris-manager-client agent start <agent-id>
   ciris-manager-client agent stop <agent-id>
   ciris-manager-client agent restart <agent-id>

   # Graceful shutdown
   ciris-manager-client agent shutdown <agent-id> --message "Maintenance"

   # View logs
   ciris-manager-client agent logs <agent-id> --lines 50 --follow

   # Check versions
   ciris-manager-client agent versions
   ciris-manager-client agent versions --agent-id datum
   ```

2. **Configuration Management** (`ciris-manager-client config <command>`)
   ```bash
   # Get agent configuration
   ciris-manager-client config get <agent-id>

   # Update configuration
   ciris-manager-client config update <agent-id> --env KEY=VALUE

   # Export/Import configuration
   ciris-manager-client config export <agent-id> --output config.json
   ciris-manager-client config import config.json

   # Backup/Restore all configurations
   ciris-manager-client config backup --output backup.json
   ciris-manager-client config restore backup.json
   ```

3. **Inspection & Validation** (`ciris-manager-client inspect <command>`)
   ```bash
   # Inspect specific agent
   ciris-manager-client inspect agent <agent-id> --check-health

   # Inspect server
   ciris-manager-client inspect server scout

   # Validate configuration file
   ciris-manager-client inspect validate config.yml

   # Full system inspection
   ciris-manager-client inspect system
   ```

**Output Formats:**
- `--format table` (default): Pretty-printed tables
- `--format json`: Machine-readable JSON
- `--format yaml`: YAML output

**Global Options:**
- `--api-url`: Override API URL (default: https://agents.ciris.ai)
- `--token`: Override auth token
- `--quiet`: Suppress non-essential output
- `--verbose`: Enable verbose logging

**Example Workflow:**
```bash
# Check agent status
ciris-manager-client agent list

# View specific agent details
ciris-manager-client agent get scout-remote-test-dahrb9

# Export configuration for backup
ciris-manager-client config export datum --output datum-backup.json

# Inspect agent health
ciris-manager-client inspect agent datum --check-health

# View recent logs
ciris-manager-client agent logs datum --lines 100
```

**Note:** This client tool (`ciris_manager_client/`) is distinct from the old `ciris_manager/cli_client.py` file, which has been removed. Always use `ciris-manager-client` for command-line operations.

## Development Best Practices

- Activate venv before running python commands.

## Architecture Overview

CIRISManager is a lightweight systemd service that manages CIRIS agent lifecycles through Docker containers.

### Core Components

1. **Container Management** (`core/container_manager.py`)
   - Monitors Docker containers running CIRIS agents
   - Handles container lifecycle (start, stop, restart)
   - Automatically pulls latest images when configured

2. **Crash Loop Detection** (`core/watchdog.py`)
   - Detects when containers crash repeatedly (3 crashes in 5 minutes)
   - Prevents infinite restart loops
   - Provides notifications for crash loops

3. **API Service** (`api/routes.py`)
   - RESTful API at `/manager/v1/*`
   - Agent discovery and health monitoring
   - OAuth authentication integration

4. **Agent Registry** (`agent_registry.py`)
   - Maintains metadata about registered agents
   - Tracks agent configuration and state
   - Persists data to `metadata.json`

5. **Port Management** (`port_manager.py`)
   - Allocates unique ports for each agent
   - Prevents port conflicts
   - Tracks port assignments

6. **Nginx Integration** (`nginx_manager.py`)
   - Generates reverse proxy configurations
   - Manages SSL certificates
   - Routes traffic to agents

7. **Deployment Orchestrator** (`deployment_orchestrator.py`)
   - Receives CD notifications from GitHub Actions
   - Orchestrates canary deployments (explorers → early adopters → general)
   - Coordinates graceful agent shutdowns
   - Tracks deployment progress
   - Respects agent update decisions

### CD/Deployment Architecture

CIRISManager handles all deployment orchestration through a clean API:

1. **Single API Call from CD**:
   ```bash
   POST /manager/v1/updates/notify
   {
       "agent_image": "ghcr.io/cirisai/ciris-agent:latest",
       "gui_image": "ghcr.io/cirisai/ciris-gui:latest",
       "message": "Security update available",
       "strategy": "canary"
   }
   ```

2. **Deployment Strategies**:
   - **Canary**: Staged rollout (10% explorers → 20% early adopters → 70% general)
   - **Immediate**: All agents at once (emergency updates)
   - **Manual**: Agents update on their own schedule

3. **Agent Update Flow**:
   - Manager calls agent's `/v1/system/update` endpoint
   - Agent responds with decision: accept/defer/reject
   - Manager respects agent autonomy
   - Docker's restart policy handles container swap

4. **Progress Tracking**:
   ```bash
   GET /manager/v1/updates/status
   ```
   Returns deployment progress, agent counts, and current phase.

### Configuration

Configuration uses a YAML file with these main sections:
- `docker`: Docker compose file location
- `watchdog`: Crash detection parameters
- `container_management`: Update intervals and image pulling
- `api`: API server host and port
- `manager`: Agent directory and other settings

### Agent Discovery

The manager discovers agents through:
1. Docker labels on containers
2. Docker compose file parsing
3. Manual registration via API

### Authentication Flow

OAuth integration supports:
- Google OAuth provider
- JWT token generation
- Permission management per agent
- Secure token storage

## Key Development Patterns

### Async/Await Usage
All I/O operations use async/await for non-blocking execution:
- Docker API calls
- File operations (using aiofiles)
- HTTP requests (using httpx)

### Error Handling
- All Docker operations wrapped in try/except blocks
- Graceful degradation when Docker is unavailable
- Detailed logging for debugging

### Testing Approach
- Unit tests with pytest and pytest-asyncio
- Mock Docker API responses
- Test fixtures for common scenarios
- Coverage target: 80%+

## Integration Points

### Docker Integration
- Requires Docker socket access (`/var/run/docker.sock`)
- Works with both standalone containers and docker-compose
- Supports container labels for metadata

### CIRIS Agent Integration
- Expects agents to follow CIRIS container conventions
- Monitors agent health endpoints
- Manages agent networking and routing

### GUI Architecture

**Two Separate GUIs:**
1. **Manager GUI**: Static HTML/JS/CSS served by nginx at `/`
   - Shows agent list, status, resource usage
   - Start/stop agents, configuration
   - Lives in CIRISManager/static/

2. **Agent GUI**: React app in container from CIRISAgent
   - Multi-tenant: accessed through main interface at `/`
   - Chat interface for interacting with agents
   - Agent selection available from main GUI interface
   - API access: `/api/{agent_id}/v1/` endpoints

**Container Count:**
- N agent containers (one per agent)
- 1 GUI container (shared, multi-tenant)
- 1 nginx container
- 0 manager GUI containers (static files)

## Production Deployment

### Production Server Access

**Main Server (agents.ciris.ai):**
```bash
ssh -i ~/.ssh/ciris_deploy root@108.61.119.117

# Note: Use IP address for SSH, not domain (Cloudflare proxied)
# Domain: agents.ciris.ai
# Public IP: 108.61.119.117
# User: root
# Key: ~/.ssh/ciris_deploy

# CIRIS deployment location: /opt/ciris
```

**Scout Server (scoutapi.ciris.ai):**
```bash
ssh -i ~/.ssh/ciris_deploy root@207.148.14.113

# Independent container host for additional agent capacity
# Domain: scoutapi.ciris.ai
# Public IP: 207.148.14.113
# VPC IP: 10.2.96.4 (for Docker API access from main server)
# User: root
# Key: ~/.ssh/ciris_deploy

# Architecture:
# - Runs own nginx container for scoutapi.ciris.ai
# - Hosts agent containers managed remotely by main CIRISManager
# - Docker API exposed on VPC IP:2376 with TLS
# - Cloudflare routes scoutapi.ciris.ai traffic directly here (not via main)
```

**Scout2 Server:**
```bash
ssh -i ~/.ssh/ciris_deploy root@104.207.141.1

# Second independent container host for additional agent capacity
# Public IP: 104.207.141.1
# User: root
# Key: ~/.ssh/ciris_deploy

# Architecture:
# - Additional agent hosting capacity
# - Managed remotely by main CIRISManager
# - Docker API exposed for remote management
```

### Agent API Authentication
When making API calls to agents, use the centralized auth system:
```python
from ciris_manager.agent_auth import get_agent_auth

# Get auth headers for an agent
auth = get_agent_auth()
headers = auth.get_auth_headers("datum")

# Make authenticated request
response = httpx.get(f"http://localhost:{port}/v1/agent/status", headers=headers)
```

The auth system automatically:
- Uses service tokens when available (encrypted in agent registry)
- Falls back to default admin credentials for legacy agents
- Handles token decryption securely
- Implements exponential backoff for failed authentication attempts
- Auto-detects authentication format preferences (service: prefix vs raw token)
- Circuit breaker pattern prevents auth spam after repeated failures

#### Extracting Agent Service Tokens

To get the decrypted service token for a specific agent (useful for external tools):

```bash
# Connect to production server
ssh -i ~/.ssh/ciris_deploy root@108.61.119.117

# Use CIRISManager's crypto system to decrypt tokens properly
# Note: Replace [REDACTED] with actual values from production environment
cd /opt/ciris-manager && env MANAGER_JWT_SECRET="[REDACTED]" CIRIS_ENCRYPTION_SALT="[REDACTED]" ./venv/bin/python3 -c "
import sys
import json
sys.path.insert(0, '/opt/ciris-manager')
from ciris_manager.crypto import get_token_encryption

# Get the encrypted token for the agent
with open('/opt/ciris/agents/metadata.json') as f:
    metadata = json.load(f)

agent_id = 'echo-nemesis-v2tyey'  # Replace with actual agent ID
if agent_id in metadata.get('agents', {}):
    encrypted_token = metadata['agents'][agent_id].get('service_token')
    if encrypted_token:
        try:
            encryption = get_token_encryption()
            decrypted_token = encryption.decrypt_token(encrypted_token)
            port = metadata['agents'][agent_id].get('port', 'unknown')
            print(f'Agent ID: {agent_id}')
            print(f'Port: {port}')
            print(f'Service Token: {decrypted_token}')
            print(f'API Endpoint: https://agents.ciris.ai/api/{agent_id}/v1/')
        except Exception as e:
            print(f'Error decrypting token: {e}')
    else:
        print(f'No service token found for {agent_id}')
else:
    print(f'Agent {agent_id} not found')
"
```

**Example output format:**
```bash
# Example for echo-nemesis
Agent ID: echo-nemesis-v2tyey
Port: 8009
Service Token: [REDACTED-EXAMPLE-TOKEN-abc123]
API Endpoint: https://agents.ciris.ai/api/echo-nemesis-v2tyey/v1/

# Example for datum
Agent ID: datum
Port: 8001
Service Token: [REDACTED-EXAMPLE-TOKEN-xyz789]
API Endpoint: https://agents.ciris.ai/api/datum/v1/
```

**Security Notes:**
- Service tokens are encrypted at rest in metadata.json
- Encryption key is stored securely in the systemd service file
- Only root access on production server can decrypt tokens
- Tokens should be handled securely and not logged in plaintext

### Production Directory Structure
```
/opt/ciris/
├── agents/          # Agent configurations and data
├── nginx/           # Nginx configurations
└── nginx-new/       # Nginx staging configurations

/opt/ciris-manager/  # CIRISManager installation
```

### Container Naming Convention
Production containers follow the naming pattern:
- `ciris-nginx` - Reverse proxy
- `ciris-gui` - Frontend interface
- `ciris-agent-{name}` - Individual agents (e.g., ciris-agent-datum)

### CIRISManager Service
CIRISManager runs as a systemd service, NOT as a Docker container:
```bash
# Check service status
systemctl status ciris-manager

# View service logs
journalctl -u ciris-manager -f

# Restart service (if needed)
systemctl restart ciris-manager

# Service configuration
/etc/systemd/system/ciris-manager.service
```

The manager service:
- Runs directly on the host (not in Docker)
- Manages Docker containers via Docker socket
- Provides API on port 8888
- Generates nginx configurations
- Handles deployments and monitoring

### Checking Production Status
```bash
# View running CIRIS containers
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep ciris

# Check container health
docker inspect ciris-agent-datum --format='{{.State.Health.Status}}'

# View container logs
docker logs ciris-agent-datum --tail 50 -f
```

### New Agent Deployment

1. **Prepare Environment File**
   Create `.env` file for the new agent with required variables:
   ```env
   CIRIS_AGENT_NAME=myagent
   CIRIS_API_PORT=8081
   OPENAI_API_KEY=your-key
   # Add other agent-specific variables
   ```

2. **Add Agent to Docker Compose**
   Update the docker-compose file in `/opt/ciris` to include the new agent service.

3. **Deploy New Agent**
   ```bash
   cd /opt/ciris
   docker-compose up -d ciris-agent-myagent
   ```

4. **Update Nginx Configuration**
   The CIRISManager will automatically detect the new agent and update nginx routing.

### Monitoring and Maintenance
- Container health is monitored by CIRISManager watchdog
- Crash loops are detected (3 crashes in 5 minutes)
- Nginx config is auto-generated when agents change
- Agent metadata stored in `/opt/ciris/agents/`

## Nginx Management

### How Nginx Integration Works

CIRISManager generates **complete nginx.conf files** for all routing:

1. **Configuration Generation**
   - Manager writes to `/home/ciris/nginx/nginx.conf`
   - Contains ALL routes: Manager GUI, Agent GUI, APIs
   - Single file, no includes, no complexity

2. **Volume Mount Strategy**
   ```
   Host: /home/ciris/nginx/nginx.conf → Container: /etc/nginx/nginx.conf:ro
   ```
   **CRITICAL**: Config must be written in-place to preserve inode. Using `os.rename()`
   or atomic replacement breaks Docker bind mounts - the container will not see updates.

3. **Update Flow**
   ```
   Agent change detected → Generate nginx.conf → Write in-place → Validate → Reload nginx
                                                                    ↓
                                                               (rollback if invalid)
   ```

4. **Route Structure**
   - `/` → Manager GUI (static files)
   - `/agent/{agent_id}` → Agent GUI (multi-tenant container)
   - `/manager/v1/*` → Manager API (port 8888)
   - `/api/{agent_id}/*` → Individual agents (dynamic ports)
   - **NO DEFAULT ROUTE** - every API call must specify agent

5. **Multi-Tenant API Routing**
   - Client calls: `/api/{agent_id}/agent/interact` (no `/v1/` prefix)
   - Nginx pattern: `/api/{agent_id}/(.*)` → `http://agent_{agent_id}/$1`
   - Agent receives: `/v1/agent/interact`
   - SDK automatically handles prefix stripping in managed mode

### Troubleshooting Nginx Issues

**Config not updating:**
```bash
# Check if nginx.conf exists and is readable
ls -la /home/ciris/nginx/nginx.conf

# Verify nginx container can see the config
docker exec ciris-nginx cat /etc/nginx/nginx.conf | head -20

# Check nginx error logs
docker logs ciris-nginx --tail 50
```

**Validation failures:**
```bash
# Test config manually
docker exec ciris-nginx nginx -t

# Check generated config content
cat /home/ciris/nginx/nginx.conf
```

**Permissions issues:**
- Manager needs write access to `/home/ciris/nginx/`
- Nginx container needs read access via volume mount
- Default owner should be the user running CIRISManager

### Nginx Architecture

**Single Configuration File:**
CIRISManager generates one complete nginx.conf that includes:
- SSL/TLS configuration
- Manager GUI (static files at `/`)
- Agent GUI routing (`/agent/{agent_id}`)
- Manager API (`/manager/v1/*`)
- Agent APIs (`/api/{agent_id}/*`)

**No Dual Config Issues:**
- One file: `/home/ciris/nginx/nginx.conf`
- One process writes it: CIRISManager
- One place to debug: the single config file

**Container Architecture:**
- Nginx container: Lives in CIRISManager, handles all routing
- Agent containers: Serve API at `/v1/*` internally
- GUI container: Multi-tenant, serves all agents at `/agent/{id}`
- Manager GUI: Static files served directly by nginx

## Multi-Server Architecture

CIRISManager supports deploying agents across multiple physical servers while maintaining centralized management from the main server.

### Server Types

**Main Server** (`agents.ciris.ai` / 108.61.119.117):
- Runs CIRISManager service (systemd, not Docker)
- Hosts nginx with **FULL deployment** (Manager GUI + Agent GUI + API routing)
- Runs local agent containers
- Manages remote servers via Docker API over TLS
- Stores agent registry (`/opt/ciris/agents/metadata.json`)

**Remote Servers** (e.g., `scoutapi.ciris.ai` / 207.148.14.113):
- Runs nginx container with **API_ONLY deployment** (no GUI routes)
- Runs agent containers assigned via `server_id` in registry
- No CIRISManager installation needed
- Docker daemon exposes TLS API on VPC IP:2376
- Receives nginx config deployments via Docker exec

### Configuration

Multi-server configuration in `/etc/ciris-manager/config.yml`:

```yaml
servers:
  - server_id: main
    hostname: agents.ciris.ai
    is_local: true
    # Main server - runs CIRISManager directly on host

  - server_id: scout
    hostname: scoutapi.ciris.ai
    is_local: false
    public_ip: 207.148.14.113
    vpc_ip: 10.2.96.4                    # Used for Docker API and agent HTTP calls
    docker_host: https://10.2.96.4:2376  # TLS-secured Docker API
    tls_ca: /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/ca.pem
    tls_cert: /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-cert.pem
    tls_key: /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-key.pem
```

### Docker API Security

Remote Docker daemons expose TLS-secured API:

```bash
# On remote server (scoutapi.ciris.ai):
dockerd -H tcp://0.0.0.0:2376 --tlsverify \
  --tlscacert=/etc/docker/ca.pem \
  --tlscert=/etc/docker/server-cert.pem \
  --tlskey=/etc/docker/server-key.pem
```

- Certificate-based authentication (CA + client cert + client key)
- Manager connects via **VPC IP** (10.2.96.4) not public IP for security
- Certificates stored in `/etc/ciris-manager/docker-certs/{hostname}/`
- Used for: container management, nginx config deployment, log viewing

### Agent Discovery and Grouping

**Agent Registry** stores `server_id` for each agent:

```json
{
  "agents": {
    "datum": {
      "server_id": "main",
      "port": 8001
    },
    "scout-remote-5r5ft8": {
      "server_id": "scout",
      "port": 8000
    }
  }
}
```

**Discovery Process** (`manager.py:update_nginx_config()`):

```python
# 1. Discover ALL agents across ALL servers
discovery = DockerAgentDiscovery(
    agent_registry=self.agent_registry,
    docker_client_manager=self.docker_client
)
all_agents = discovery.discover_agents()  # Queries main + scout Docker APIs

# 2. Group agents by server_id from registry
agents_by_server = {}
for agent in all_agents:
    agent_info = self.agent_registry.get_agent(agent.agent_id)
    server_id = agent_info.server_id  # "main" or "scout"
    agents_by_server[server_id].append(agent)

# 3. Update nginx on EACH server with its agents
for server_id, nginx_manager in self.nginx_managers.items():
    server_agents = agents_by_server.get(server_id, [])
    if server_config.is_local:
        # Main: write to /home/ciris/nginx/nginx.conf
        nginx_manager.update_config(server_agents)
    else:
        # Remote: deploy via Docker API
        config = nginx_manager.generate_config(server_agents)
        docker_client = self.docker_client.get_client(server_id)
        nginx_manager.deploy_remote_config(config, docker_client, "ciris-nginx")
```

### Remote Nginx Deployment

**Deployment Flow** (`nginx_manager.py:deploy_remote_config()`):

```python
def deploy_remote_config(config_content: str, docker_client, container_name: str):
    container = docker_client.containers.get(container_name)

    # Step 1: Write config to temp file (base64 to avoid shell escaping)
    encoded = base64.b64encode(config_content.encode()).decode()
    container.exec_run(f"sh -c 'echo {encoded} | base64 -d > /tmp/nginx.conf.new'")

    # Step 2: Validate config
    result = container.exec_run("nginx -t -c /tmp/nginx.conf.new")
    if result.exit_code != 0:
        raise ValidationError(result.output)

    # Step 3: Atomic update (write directly, preserving file)
    container.exec_run("cat /tmp/nginx.conf.new > /etc/nginx/nginx.conf")

    # Step 4: Reload nginx
    container.exec_run("nginx -s reload")
```

**Why base64 encoding?** Avoids shell escaping issues with special characters in nginx config (quotes, dollar signs, etc.)

**Why cat instead of mv?** Preserves the file inode if nginx is watching it.

### Remote Nginx Config Generation

**Main Server** (`hostname: agents.ciris.ai`):
- Full UI routes: Manager GUI (`/`), Agent GUI (`/agent/{id}`), Jailbreaker
- Manager API: `/manager/v1/*`
- OAuth routes: `/manager/v1/oauth/*`
- Agent API routes: `/api/{agent_id}/v1/*`
- Agent OAuth routes: `/v1/auth/oauth/{agent_id}/*`

**Remote Servers** (`hostname: scoutapi.ciris.ai`):
- **NO UI routes** - only API routing
- Agent API routes: `/api/{agent_id}/v1/*`
- Agent OAuth routes: `/v1/auth/oauth/{agent_id}/*`
- Root path: `return 404 "Agent server - API only\n"`

**Example Remote Nginx Config** for `scout-remote-5r5ft8` on port 8000:

```nginx
# OAuth callback route
location ~ ^/v1/auth/oauth/scout-remote-5r5ft8/(.+)/callback$ {
    proxy_pass http://agent_scout-remote-5r5ft8/v1/auth/oauth/$1/callback$is_args$args;
    proxy_set_header Host $host;
}

# Agent API routes
location ~ ^/api/scout-remote-5r5ft8/v1/(.*)$ {
    proxy_pass http://agent_scout-remote-5r5ft8/v1/$1$is_args$args;
    proxy_set_header Host $host;
}

# Upstream for agent
upstream agent_scout-remote-5r5ft8 {
    server localhost:8000;
}
```

### Agent Operations on Remote Servers

**Creating Agent on Remote Server:**

```python
# Via API or manager.create_agent()
await manager.create_agent(
    name="scout",
    template="scout",
    server_id="scout"  # Deploy to remote server
)
```

**What happens:**
1. Registry updated: `agent_id="scout-xyz", server_id="scout", port=8000`
2. Docker-compose.yml generated locally
3. Container created on remote via Docker API:
   ```python
   docker_client = self.docker_client.get_client("scout")
   docker_client.containers.run(image=image, name=name, ports={8000: 8000}, ...)
   ```
4. Admin password set via HTTP to VPC IP:
   ```python
   base_url = server_config.vpc_ip  # 10.2.96.4, not scoutapi.ciris.ai
   url = f"http://{base_url}:8000/v1/auth/login"
   ```
5. Nginx config deployed to remote via Docker exec

**Agent Discovery on Remote Server:**

```python
# DockerAgentDiscovery._discover_multi_server()
for server_id in ["main", "scout"]:
    client = docker_client_manager.get_client(server_id)  # Gets Docker API client
    containers = client.containers.list()  # Lists containers on this server

    for container in containers:
        env = container.attrs.get("Config", {}).get("Env", [])
        if "CIRIS_AGENT_ID" in env:
            agent_info = _extract_agent_info(container, server_id=server_id)
            all_agents.append(agent_info)
```

**URL Construction for Remote Agent Calls:**

```python
# When calling agent APIs (health, status, updates)
if server_id == "main":
    base_url = "localhost"
else:
    server_config = docker_client.get_server_config(server_id)
    base_url = server_config.vpc_ip  # Use VPC IP, not hostname!

url = f"http://{base_url}:{port}/v1/agent/status"
# For scout: http://10.2.96.4:8000/v1/agent/status
```

**Why VPC IP?** Remote agent containers are not publicly accessible. Only nginx on the remote server exposes them via `scoutapi.ciris.ai`. Manager must use VPC networking.

### Troubleshooting Multi-Server Setup

**Check remote Docker connection:**
```bash
# From main server
docker --host https://10.2.96.4:2376 \
  --tlsverify \
  --tlscacert /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/ca.pem \
  --tlscert /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-cert.pem \
  --tlskey /etc/ciris-manager/docker-certs/scoutapi.ciris.ai/client-key.pem \
  ps --filter 'name=ciris'
```

**Check remote nginx container:**
```bash
# Test nginx config on remote
docker --host https://10.2.96.4:2376 --tlsverify [...] exec ciris-nginx nginx -t

# View remote nginx logs
docker --host https://10.2.96.4:2376 --tlsverify [...] logs ciris-nginx --tail 50
```

**Check agent grouping:**
```bash
# Manager logs show agent counts per server
journalctl -u ciris-manager | grep "Updating nginx config for server"
# Expected:
#   Updating nginx config for server main with 6 agents
#   Updating nginx config for server scout with 2 agents
```

**Check remote nginx deployment:**
```bash
# Manager logs show deployment status
journalctl -u ciris-manager | grep "deploy.*remote"
# Success: "✅ Deployed nginx config to remote server scout with 2 agents"
# Failure: "❌ Failed to deploy nginx config to remote server scout"
```

**Common Issues:**

1. **"Updating nginx config for server scout with 0 agents"**
   - **Cause**: Agent registry has `server_id: "scout"` but Docker discovery didn't find the agent
   - **Fix**: Check agent container is running on remote server and has `CIRIS_AGENT_ID` env var

2. **"❌ Failed to deploy nginx config to remote server scout"**
   - **Cause**: Docker API connection failed or nginx container not found
   - **Fix**: Test Docker API connectivity, verify `ciris-nginx` container exists on remote

3. **OAuth URLs return 404 on remote (e.g., `/v1/auth/oauth/google/login`)**
   - **Cause**: Nginx config on remote server has no routes for this agent
   - **Fix**: Check nginx deployment succeeded, verify agent appears in `agents_by_server["scout"]`

4. **Agent API calls fail from manager to remote agent**
   - **Cause**: Using `localhost` or public hostname instead of VPC IP
   - **Fix**: Ensure `server_config.vpc_ip` is used for remote agent HTTP calls

### Multi-Server Best Practices

1. **Always use VPC IPs** for manager-to-remote-agent communication
2. **Store `server_id` in registry** immediately when creating agent
3. **Monitor nginx deployment logs** after agent changes
4. **Test Docker API connectivity** before adding new remote servers
5. **Keep nginx containers named `ciris-nginx`** on all servers for consistency
