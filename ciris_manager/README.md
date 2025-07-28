# CIRISManager

Lightweight agent lifecycle management service for CIRIS agents.

## Status (July 20, 2025)
- **Phase 1**: Core Watchdog and Container Management ✅
- **Phase 2**: API for Agent Discovery ✅
- **Production**: Running on agents.ciris.ai
- **Integration**: Full CI/CD and GUI support

## Phase 2 Complete: API for Agent Discovery ✅

The API provides:
- `/manager/v1/agents` - List all agents with status
- `/manager/v1/agents/{agent_id}` - Get specific agent details
- `/manager/v1/agents/{agent_id}/health` - Agent health check
- `/manager/v1/system/health` - Manager health status

Production runs API-only mode via `deployment/run-ciris-manager-api.py`

## Phase 1 Complete: Core Watchdog and Container Management ✅

### What's Implemented

1. **Container Manager** (`core/container_manager.py`)
   - Runs `docker-compose up -d` every 60 seconds
   - Pulls latest images automatically
   - Detects when updates are available
   - Leverages Docker's `restart: unless-stopped` behavior

2. **Crash Loop Watchdog** (`core/watchdog.py`)
   - Monitors containers every 30 seconds
   - Detects crash loops (3 crashes in 5 minutes)
   - Stops containers to prevent infinite restarts
   - Tracks crash history with timestamps

3. **Configuration System** (`config/settings.py`)
   - Pydantic-based configuration
   - YAML file support
   - Sensible defaults
   - Validation and type safety

4. **Main Service** (`manager.py`)
   - Coordinates all components
   - Graceful shutdown handling
   - Status reporting
   - Signal handling (SIGTERM/SIGINT)

5. **CLI Interface** (`__main__.py`)
   - Generate default config: `ciris-manager --generate-config`
   - Validate config: `ciris-manager --validate-config`
   - Run service: `ciris-manager --config /path/to/config.yml`

### How It Works

The key insight is using Docker's natural behavior:

1. Container exits (any reason)
2. Docker's `restart: unless-stopped` policy:
   - Exit code 0 → Container stays stopped
   - Non-zero exit → Docker tries to restart
3. CIRISManager runs `docker-compose up -d` periodically:
   - Stopped containers start with **latest image**
   - Running containers are **not affected**

This eliminates complex staging logic!

### Installation

```bash
# Install in development mode
pip install -e .

# Or install from setup
python setup_manager.py install
```

### Usage

1. Generate config file:
```bash
ciris-manager --generate-config --config /etc/ciris-manager/config.yml
```

2. Edit config as needed:
```yaml
manager:
  port: 9999
  host: 127.0.0.1

docker:
  compose_file: /home/ciris/CIRISAgent/deployment/docker-compose.yml

watchdog:
  check_interval: 30
  crash_threshold: 3
  crash_window: 300

container_management:
  interval: 60
  pull_images: true
```

3. Run the service:
```bash
ciris-manager --config /etc/ciris-manager/config.yml
```

### Docker Deployment

Build the container:
```bash
docker build -f Dockerfile.manager -t ciris-manager .
```

Run with Docker socket access:
```bash
docker run -d \
  --name ciris-manager \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /etc/ciris-manager:/etc/ciris-manager \
  -v /home/ciris/CIRISAgent:/home/ciris/CIRISAgent:ro \
  ciris-manager
```

### Systemd Service

Install the service:
```bash
sudo cp deployment/ciris-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ciris-manager
sudo systemctl start ciris-manager
```

### Testing

Run unit tests:
```bash
python test_ciris_manager.py
```

Run integration test (requires Docker):
```bash
python test_ciris_manager_integration.py
```

## Next Phases

- **Phase 2**: API endpoints for agent discovery
- **Phase 3**: Agent creation with WA signatures  
- **Phase 4**: GUI integration
- **Phase 5**: Local auth for update notifications

The core container management and crash loop detection is now complete and ready for use!