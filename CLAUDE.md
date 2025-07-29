# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

# API-only mode (no container management)
python deployment/run-ciris-manager-api.py

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

### GUI Integration
- Integrates with CIRIS GUI from CIRISAgent repository
- GUI runs as separate container on port 3000
- Nginx routes traffic between GUI and Manager API