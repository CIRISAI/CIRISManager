# CIRISManager

Lightweight agent lifecycle management service for CIRIS agents.

## Overview

CIRISManager is a standalone service that manages the lifecycle of CIRIS agents. It provides:

- Per-agent container lifecycle management with individual docker-compose files
- Crash loop detection and automatic recovery
- REST API for agent creation, discovery, and health monitoring
- OAuth authentication with development/production modes
- Optional nginx reverse proxy integration
- Port allocation and management

## Quick Start

```bash
# One-line setup
./quickstart.sh

# Set up environment for local development
export CIRIS_MANAGER_CONFIG=$(pwd)/config.yml
export CIRIS_AUTH_MODE=development  # Optional: skip OAuth in development

# Or manually:
make dev     # Install development dependencies  
make test    # Run tests
make run-api # Start the API server (requires config export above)
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development guidelines.

## Features

### Core Container Management
- Creates and manages individual docker-compose.yml per agent
- Detects and handles crash loops (3 crashes in 5 minutes)
- Automatically pulls latest images from configured registry
- Graceful shutdown handling

### API Services  
- RESTful API at `/manager/v1/*` for agent operations
- Health monitoring endpoints
- OAuth integration with development bypass option
- Template-based agent creation

### Architecture
- Each agent runs in its own isolated environment
- Agents are created from pre-approved templates
- Port allocation prevents conflicts between agents
- Optional nginx integration for production routing

## Installation

### Production Deployment

```bash
# Quick install - run deployment script directly
curl -sSL https://raw.githubusercontent.com/CIRISAI/ciris-manager/main/deployment/deploy.sh | bash

# Or clone and run manually
git clone https://github.com/CIRISAI/ciris-manager.git /opt/ciris-manager
cd /opt/ciris-manager
./deployment/deploy.sh
```

### Development Setup

```bash
# Clone the repository
git clone https://github.com/CIRISAI/ciris-manager.git
cd ciris-manager

# Run development setup
./deployment/setup-development.sh

# Start API server
./run-api.sh
```

## Configuration

Generate a default configuration file:

```bash
ciris-manager --generate-config --config /etc/ciris-manager/config.yml
```

Example configuration:

```yaml
manager:
  port: 8888
  host: 127.0.0.1
  agents_directory: /opt/ciris/agents
  templates_directory: ./agent_templates

auth:
  mode: development  # or 'production' for OAuth

nginx:
  enabled: false  # Set to true for production
  config_dir: /etc/nginx/sites-enabled
  
docker:
  registry: ghcr.io/cirisai
  image: ciris-agent:latest

watchdog:
  check_interval: 30
  crash_threshold: 3
  crash_window: 300

ports:
  start: 8000
  end: 8999
  reserved: [8080, 8888]

## Usage

### Running the Service

```bash
# Run with configuration file
ciris-manager --config /etc/ciris-manager/config.yml

# Run API-only mode
python deployment/run-ciris-manager-api.py
```

### API Endpoints

- `GET /manager/v1/health` - Manager health check
- `GET /manager/v1/status` - Manager status and components  
- `GET /manager/v1/agents` - List all agents (Docker discovery)
- `GET /manager/v1/agents/{agent_name}` - Get specific agent details
- `POST /manager/v1/agents` - Create new agent from template
- `DELETE /manager/v1/agents/{agent_id}` - Delete agent and cleanup
- `GET /manager/v1/templates` - List available agent templates
- `GET /manager/v1/ports/allocated` - Show port allocations

### Authentication

- **Development mode**: No auth required (`auth.mode: development`)
- **Production mode**: Google OAuth required (`auth.mode: production`)
- OAuth endpoints: `/manager/v1/oauth/login`, `/manager/v1/oauth/callback`

### Systemd Service

The deployment script automatically installs systemd services:

```bash
# Start services
sudo systemctl start ciris-manager      # Full manager with watchdog
sudo systemctl start ciris-manager-api  # API-only mode

# Enable on boot
sudo systemctl enable ciris-manager

# Check status
sudo systemctl status ciris-manager
journalctl -u ciris-manager -f

# Update from Git
ciris-manager-update
```

## Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test module
pytest tests/ciris_manager/test_manager.py
```

### Frontend Development

```bash
cd frontend
npm install
npm run dev
```

## Deployment

### Production Deployment

The manager is designed to run alongside CIRIS agents on production servers:

1. **Installation**: Clone repository to `/opt/ciris-manager`
2. **Configuration**: Edit `/etc/ciris-manager/config.yml`
3. **Service**: Runs as systemd service with automatic restarts
4. **Updates**: Pull from Git and restart service

### Agent Management Architecture

Unlike traditional approaches, CIRISManager creates isolated environments:

```
/opt/ciris/agents/
├── scout-abc123/
│   ├── docker-compose.yml  # Generated per-agent
│   ├── data/              # Agent data volume
│   └── logs/              # Agent logs
└── sage-xyz789/
    ├── docker-compose.yml
    ├── data/
    └── logs/
```

Each agent gets:
- Unique port allocation (8000-8999 range)
- Individual docker-compose configuration
- Isolated data and log volumes
- Optional nginx routing

### Updating

To update to the latest version:

```bash
# Use the provided update script
ciris-manager-update

# Or manually
cd /opt/ciris-manager
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
systemctl restart ciris-manager
```

## Architecture

CIRISManager follows a modular architecture:

- **Core**: Container management and watchdog services
- **API**: FastAPI-based REST endpoints
- **Auth**: OAuth and permission management
- **Nginx**: Dynamic routing configuration for agents

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

[Same license as CIRIS Agent]

## Related Projects

- [CIRIS Agent](https://github.com/CIRISAI/CIRISAgent) - The main CIRIS agent repository
- [CIRIS GUI](https://github.com/CIRISAI/CIRISAgent/tree/main/CIRISGUI) - The main GUI that integrates with this manager