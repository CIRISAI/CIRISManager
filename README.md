# CIRISManager

Lightweight agent lifecycle management service for CIRIS agents.

## Overview

CIRISManager is a standalone service that manages the lifecycle of CIRIS agents. It provides:

- Container management and crash loop detection
- API for agent discovery and health monitoring
- OAuth authentication and permission management
- Nginx configuration management
- GUI components for agent management

## Quick Start

```bash
# One-line setup
./quickstart.sh

# Set up environment for local development
export CIRIS_MANAGER_CONFIG=$(pwd)/config.yml

# Or manually:
make dev     # Install development dependencies
make test    # Run tests
make run-api # Start the API server (requires config export above)
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed development guidelines.

## Features

### Core Container Management
- Monitors Docker containers running CIRIS agents
- Detects and handles crash loops (3 crashes in 5 minutes)
- Automatically pulls latest images
- Graceful shutdown handling

### API Services
- RESTful API for agent discovery
- Health monitoring endpoints
- OAuth integration for secure access
- Permission management system

### Frontend Components
- TypeScript client library
- React components for agent management
- Real-time agent status updates

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

docker:
  compose_file: /path/to/docker-compose.yml

watchdog:
  check_interval: 30
  crash_threshold: 3
  crash_window: 300

container_management:
  interval: 60
  pull_images: true
```

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
- `GET /manager/v1/agents` - List all agents
- `GET /manager/v1/agents/{agent_name}` - Get specific agent details
- `POST /manager/v1/agents` - Create new agent (requires auth)
- `DELETE /manager/v1/agents/{agent_id}` - Delete agent (requires auth)
- `GET /manager/v1/templates` - List available templates
- `GET /manager/v1/ports/allocated` - Show allocated ports

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

Features:
- Monitor multiple agents via docker-compose
- Provide centralized API access to agent status
- Handle OAuth authentication for secure access
- Integrate with nginx for reverse proxy support

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
- **Frontend**: TypeScript/React components

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