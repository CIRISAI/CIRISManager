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
   - Multi-tenant: `/agent/{agent_id}`
   - Chat interface for interacting with agents
   - Detects mode (standalone vs managed) from URL

**Container Count:**
- N agent containers (one per agent)
- 1 GUI container (shared, multi-tenant)
- 1 nginx container
- 0 manager GUI containers (static files)

## Production Deployment

### Production Server Access
```bash
# SSH connection details
ssh -i ~/.ssh/ciris_deploy root@108.61.119.117

# Note: Use IP address for SSH, not domain (Cloudflare proxied)
# Domain: agents.ciris.ai
# IP: 108.61.119.117
# User: root
# Key: ~/.ssh/ciris_deploy

# CIRIS deployment location: /opt/ciris
```

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
   The nginx container sees config changes immediately via volume mount.

3. **Update Flow**
   ```
   Agent change detected → Generate nginx.conf → Validate config → Reload nginx
                                                      ↓
                                                 (rollback if invalid)
   ```

4. **Route Structure**
   - `/` → Manager GUI (static files)
   - `/agent/{agent_id}` → Agent GUI (multi-tenant container)
   - `/manager/v1/*` → Manager API (port 8888)
   - `/api/{agent_id}/*` → Individual agents (dynamic ports)
   - **NO DEFAULT ROUTE** - every API call must specify agent

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
