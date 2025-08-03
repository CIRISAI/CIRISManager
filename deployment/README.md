# CIRISManager Deployment

This directory contains deployment scripts and configuration for CIRISManager.

## Deployment Strategy

CIRISManager is deployed by cloning the Git repository directly on the target server, rather than using Docker containers. This approach provides:

- Direct control over the Python environment
- Easy updates via `git pull`
- No container overhead
- Simple debugging and maintenance

## Files

### Production Deployment

- **`deploy.sh`** - Main deployment script for production servers
  - Clones/updates the repository
  - Sets up Python virtual environment
  - Installs dependencies
  - Creates systemd services
  - Generates default configuration

- **`ciris-manager.service`** - Systemd service for full manager (watchdog + API)

### Development Setup

- **`setup-development.sh`** - Sets up local development environment
  - Creates virtual environment
  - Installs dev dependencies
  - Generates development scripts
  - Sets up pre-commit hooks (optional)

### Legacy Scripts

- **`install-ciris-manager.sh`** - Legacy installation script (kept for reference)

## Usage

### Production Server Deployment

```bash
# Option 1: Direct deployment
curl -sSL https://raw.githubusercontent.com/CIRISAI/ciris-manager/main/deployment/deploy.sh | bash

# Option 2: Clone first, then deploy
git clone https://github.com/CIRISAI/ciris-manager.git /opt/ciris-manager
cd /opt/ciris-manager
./deployment/deploy.sh
```

### Local Development

```bash
git clone https://github.com/CIRISAI/ciris-manager.git
cd ciris-manager
./deployment/setup-development.sh
./run-api.sh
```

### Updating Production

```bash
# Using the update script
ciris-manager-update

# Or manually
cd /opt/ciris-manager
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
systemctl restart ciris-manager
```

## Configuration

After deployment, configuration is stored at `/etc/ciris-manager/config.yml`. Key settings:

```yaml
manager:
  port: 8888
  host: 127.0.0.1

docker:
  compose_file: /path/to/your/docker-compose.yml

watchdog:
  check_interval: 30
  crash_threshold: 3
  crash_window: 300
```

## Environment Variables

- `CIRIS_MANAGER_DIR` - Installation directory (default: `/opt/ciris-manager`)
- `CIRIS_MANAGER_REPO` - Git repository URL
- `CIRIS_MANAGER_BRANCH` - Git branch to deploy (default: `main`)
- `CIRIS_MANAGER_CONFIG` - Path to config file (default: `/etc/ciris-manager/config.yml`)

## Services

The systemd service is created:

**ciris-manager** - Full service with container watchdog and API

Start with:
```bash
systemctl start ciris-manager
systemctl enable ciris-manager     # Enable on boot
```

## Logs

View logs with:
```bash
journalctl -u ciris-manager -f
```
