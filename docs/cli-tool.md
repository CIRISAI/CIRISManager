# CIRIS Manager CLI Tool

A comprehensive command-line interface for managing CIRIS agents, deployments, and infrastructure.

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [Command Reference](#command-reference)
  - [Agent Management](#agent-management)
  - [Configuration Management](#configuration-management)
  - [Maintenance Mode](#maintenance-mode)
  - [OAuth Management](#oauth-management)
  - [Deployment Operations](#deployment-operations)
  - [Canary Deployments](#canary-deployments)
  - [Template Management](#template-management)
  - [Server Management](#server-management)
  - [System Operations](#system-operations)
  - [Authentication](#authentication)
  - [Inspection & Validation](#inspection--validation)
- [Configuration Files](#configuration-files)
- [Examples](#examples)

## Installation

```bash
# Install from source
pip install -e ".[dev]"

# The CLI will be available as 'ciris-cli'
ciris-cli --help
```

## Configuration

The CLI looks for authentication tokens in the following locations (in order):

1. `~/.manager_token` - Simple token file
2. `~/.config/ciris-manager/token.json` - Token with expiry
3. Environment variable `CIRIS_MANAGER_TOKEN`

API endpoint defaults to `https://agents.ciris.ai` but can be overridden:

```bash
# Set custom API endpoint
ciris-cli --api-url http://localhost:8888 agent list

# Or use environment variable
export CIRIS_MANAGER_API_URL=http://localhost:8888
```

## Command Reference

All commands support these global options:
- `--api-url URL` - Override API endpoint
- `--token TOKEN` - Override authentication token
- `--format FORMAT` - Output format: `table` (default), `json`, `yaml`
- `--quiet` - Suppress non-essential output
- `--verbose` - Enable verbose logging

### Agent Management

#### List Agents

```bash
# List all agents
ciris-cli agent list

# List agents on specific server
ciris-cli agent list --server scout

# List agents by deployment
ciris-cli agent list --deployment CIRIS_DISCORD_PILOT

# List agents by status
ciris-cli agent list --status running

# Output as JSON
ciris-cli agent list --format json

# Filter and format
ciris-cli agent list --server main --status running --format table
```

#### Get Agent Details

```bash
# Get detailed information about an agent
ciris-cli agent get datum

# Output as JSON for scripting
ciris-cli agent get datum --format json
```

#### Create Agent

```bash
# Create basic agent
ciris-cli agent create --name my-agent --template scout

# Create on specific server
ciris-cli agent create --name scout-test --template scout --server scout

# Create with environment variables
ciris-cli agent create \
  --name my-agent \
  --template scout \
  --env OAUTH_CALLBACK_BASE_URL=https://scoutapi.ciris.ai \
  --env CUSTOM_VAR=value

# Create with mock LLM
ciris-cli agent create --name test-agent --template scout --use-mock-llm

# Create with Discord enabled
ciris-cli agent create --name discord-bot --template scout --enable-discord

# Create with billing
ciris-cli agent create \
  --name paid-agent \
  --template scout \
  --billing-enabled \
  --billing-api-key sk_test_xxx
```

#### Delete Agent

```bash
# Delete agent (with confirmation)
ciris-cli agent delete scout-test-abc123

# Force delete without confirmation
ciris-cli agent delete scout-test-abc123 --force
```

#### Start/Stop/Restart Agent

```bash
# Start agent
ciris-cli agent start datum

# Stop agent
ciris-cli agent stop datum

# Restart agent
ciris-cli agent restart datum

# Graceful shutdown (allows agent to finish work)
ciris-cli agent shutdown datum --message "Maintenance window"
```

#### View Agent Logs

```bash
# View last 100 lines
ciris-cli agent logs datum

# View last N lines
ciris-cli agent logs datum --lines 500

# Follow logs (like tail -f)
ciris-cli agent logs datum --follow

# Save to file
ciris-cli agent logs datum --lines 1000 > datum.log
```

#### Agent Version Information

```bash
# Show version info for all agents
ciris-cli agent versions

# Show version for specific agent
ciris-cli agent versions --agent-id datum
```

### Configuration Management

#### Get Agent Configuration

```bash
# Get agent config
ciris-cli config get datum

# Get as JSON
ciris-cli config get datum --format json

# Get as YAML
ciris-cli config get datum --format yaml
```

#### Update Agent Configuration

```bash
# Update environment variable
ciris-cli config update datum --env NEW_VAR=value

# Update multiple environment variables
ciris-cli config update datum \
  --env VAR1=value1 \
  --env VAR2=value2

# Update from JSON file
ciris-cli config update datum --from-file config.json
```

#### Export Configuration

```bash
# Export to JSON file
ciris-cli config export datum --output datum-config.json

# Export to YAML
ciris-cli config export datum --output datum-config.yaml --format yaml

# Export all agents on a server
ciris-cli config export --server scout --output scout-agents.json
```

#### Import Configuration

```bash
# Import from file (dry run first)
ciris-cli config import datum-config.json --dry-run

# Import and create/update agent
ciris-cli config import datum-config.json

# Import with different agent ID
ciris-cli config import datum-config.json --agent-id new-datum
```

#### Backup All Configurations

```bash
# Backup all agents
ciris-cli config backup --output agents-backup.json

# Backup specific server
ciris-cli config backup --server main --output main-backup.json

# Backup with timestamp
ciris-cli config backup --output "backup-$(date +%Y%m%d).json"
```

#### Restore from Backup

```bash
# Restore all agents from backup
ciris-cli config restore agents-backup.json

# Restore specific agent from backup
ciris-cli config restore agents-backup.json --agent-id datum

# Restore with dry run
ciris-cli config restore agents-backup.json --dry-run
```

### Maintenance Mode

```bash
# Enter maintenance mode
ciris-cli maintenance enter datum --message "Database migration"

# Exit maintenance mode
ciris-cli maintenance exit datum

# Check maintenance status
ciris-cli maintenance status datum

# List all agents in maintenance
ciris-cli maintenance list
```

### OAuth Management

```bash
# Verify OAuth status
ciris-cli oauth verify datum

# Complete OAuth flow
ciris-cli oauth complete datum --code AUTH_CODE

# Check OAuth for all agents
ciris-cli oauth status
```

### Deployment Operations

#### Notify About Update

```bash
# Notify agents about new version (canary deployment)
ciris-cli deploy notify \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.0.0 \
  --gui-image ghcr.io/cirisai/ciris-gui:v2.0.0 \
  --strategy canary \
  --message "Security update with new features"

# Immediate deployment (all agents at once)
ciris-cli deploy notify \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.0.1 \
  --strategy immediate \
  --message "Critical security patch"
```

#### Launch Deployment

```bash
# Launch a pending deployment
ciris-cli deploy launch DEPLOYMENT_ID
```

#### Deployment Status

```bash
# Get current deployment status
ciris-cli deploy status

# Get specific deployment status
ciris-cli deploy status --deployment-id abc123

# Watch deployment progress
ciris-cli deploy status --follow
```

#### Pending Deployments

```bash
# List pending deployments for current agent
ciris-cli deploy pending

# List all pending deployments
ciris-cli deploy pending --all
```

#### Preview Deployment

```bash
# Preview what will happen
ciris-cli deploy preview DEPLOYMENT_ID
```

#### Deployment Events

```bash
# Show deployment events/timeline
ciris-cli deploy events DEPLOYMENT_ID

# Follow events in real-time
ciris-cli deploy events DEPLOYMENT_ID --follow
```

#### Control Deployment

```bash
# Cancel deployment
ciris-cli deploy cancel

# Reject deployment
ciris-cli deploy reject --reason "Failed smoke tests"

# Pause deployment
ciris-cli deploy pause
```

#### Rollback

```bash
# Rollback current deployment
ciris-cli deploy rollback

# List rollback options
ciris-cli deploy rollback-options

# Preview rollback
ciris-cli deploy rollback-preview DEPLOYMENT_ID

# Approve pending rollback
ciris-cli deploy approve-rollback ROLLBACK_ID
```

#### Single Agent Deploy

```bash
# Deploy to single agent
ciris-cli deploy single datum \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.0.0
```

#### Deployment History

```bash
# View deployment history
ciris-cli deploy history

# View last N deployments
ciris-cli deploy history --limit 10

# View history as JSON
ciris-cli deploy history --format json
```

#### View Changelog

```bash
# View latest changelog
ciris-cli deploy changelog

# View specific version changelog
ciris-cli deploy changelog --version v2.0.0
```

### Canary Deployments

```bash
# List canary groups
ciris-cli canary groups

# Set agent canary group
ciris-cli canary set-group datum --group explorer

# Available groups: explorer, early_adopter, general

# View version adoption statistics
ciris-cli canary adoption

# View adoption over time
ciris-cli canary adoption --history
```

### Template Management

```bash
# List available templates
ciris-cli template list

# Get template details
ciris-cli template details scout

# View default environment for template
ciris-cli template env-default scout
```

### Server Management

```bash
# List all servers
ciris-cli server list

# Get server details
ciris-cli server get main

# Get server statistics
ciris-cli server stats scout

# List agents on server
ciris-cli server agents scout

# Compare servers
ciris-cli server compare main scout
```

### System Operations

```bash
# Health check
ciris-cli system health

# Detailed status
ciris-cli system status

# View allocated ports
ciris-cli system ports

# View deployment tokens
ciris-cli system tokens
```

### Authentication

```bash
# OAuth login (opens browser)
ciris-cli auth login

# OAuth logout
ciris-cli auth logout

# Show current user
ciris-cli auth whoami

# Device code flow (for headless systems)
ciris-cli auth device

# Generate dev token (development mode only)
ciris-cli auth token --dev
```

### Inspection & Validation

These commands perform deeper inspection beyond API calls, including SSH checks.

```bash
# Inspect agent (checks Docker labels, nginx routes, health)
ciris-cli inspect agent datum

# Inspect remote agent
ciris-cli inspect agent scout-u7e9s3 --server scout

# Check specific aspects
ciris-cli inspect agent datum --check-labels
ciris-cli inspect agent datum --check-nginx
ciris-cli inspect agent datum --check-health

# Inspect server
ciris-cli inspect server scout

# Validate config file
ciris-cli inspect validate config.json

# Full system inspection
ciris-cli inspect system
```

## Configuration Files

### Agent Configuration Format (JSON)

```json
{
  "agent_id": "datum",
  "name": "datum",
  "template": "base",
  "server_id": "main",
  "port": 8001,
  "environment": {
    "OAUTH_CALLBACK_BASE_URL": "https://agents.ciris.ai",
    "GROQ_API_KEY": "gsk_xxx",
    "OPENAI_API_KEY": "sk-xxx"
  },
  "mounts": null,
  "use_mock_llm": false,
  "enable_discord": false,
  "billing_enabled": false,
  "created_at": "2024-08-20T10:30:00Z",
  "metadata": {
    "deployment": "PRODUCTION",
    "canary_group": "general"
  }
}
```

### Agent Configuration Format (YAML)

```yaml
agent_id: datum
name: datum
template: base
server_id: main
port: 8001
environment:
  OAUTH_CALLBACK_BASE_URL: https://agents.ciris.ai
  GROQ_API_KEY: gsk_xxx
  OPENAI_API_KEY: sk-xxx
use_mock_llm: false
enable_discord: false
billing_enabled: false
created_at: "2024-08-20T10:30:00Z"
metadata:
  deployment: PRODUCTION
  canary_group: general
```

### Backup File Format

```json
{
  "version": "1.0",
  "backup_date": "2025-10-13T23:00:00Z",
  "agents": [
    {
      "agent_id": "datum",
      "name": "datum",
      "template": "base",
      ...
    },
    {
      "agent_id": "scout-u7e9s3",
      "name": "scout",
      "template": "scout",
      ...
    }
  ]
}
```

## Examples

### Common Workflows

#### Deploy New Agent to Remote Server

```bash
# 1. Create agent on scout server
ciris-cli agent create \
  --name production-scout \
  --template scout \
  --server scout \
  --env OAUTH_CALLBACK_BASE_URL=https://scoutapi.ciris.ai

# 2. Verify it's working
ciris-cli inspect agent scout-xxx --server scout

# 3. Check logs
ciris-cli agent logs scout-xxx
```

#### Backup and Recreate Agent

```bash
# 1. Export existing agent config
ciris-cli config export scout-remote-test-dahrb9 --output scout-backup.json

# 2. Delete old agent
ciris-cli agent delete scout-remote-test-dahrb9 --force

# 3. Recreate from backup
ciris-cli config import scout-backup.json

# 4. Verify new agent
ciris-cli inspect agent <new-agent-id> --check-labels --check-nginx
```

#### Migrate Agent Between Servers

```bash
# 1. Export config from main server
ciris-cli config export datum --output datum-main.json

# 2. Edit config to change server_id
# Edit datum-main.json: "server_id": "scout"

# 3. Create on new server
ciris-cli config import datum-main.json --agent-id datum-scout

# 4. Test new agent
ciris-cli inspect agent datum-scout --server scout

# 5. Delete old agent if satisfied
ciris-cli agent delete datum --force
```

#### Rolling Deployment

```bash
# 1. Notify about new version
ciris-cli deploy notify \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.1.0 \
  --strategy canary \
  --message "New features: X, Y, Z"

# 2. Monitor deployment progress
ciris-cli deploy status --follow

# 3. Check events
ciris-cli deploy events <deployment-id>

# 4. If issues, rollback
ciris-cli deploy rollback
```

#### Maintenance Window

```bash
# 1. Put agents in maintenance mode
ciris-cli maintenance enter datum --message "Database upgrade"
ciris-cli maintenance enter scout-u7e9s3 --message "Database upgrade"

# 2. Perform maintenance
# ... database operations ...

# 3. Take agents out of maintenance
ciris-cli maintenance exit datum
ciris-cli maintenance exit scout-u7e9s3

# 4. Verify health
ciris-cli inspect agent datum
ciris-cli inspect agent scout-u7e9s3
```

#### Batch Operations with Shell

```bash
# Stop all agents on scout server
ciris-cli agent list --server scout --format json | \
  jq -r '.[].agent_id' | \
  xargs -I {} ciris-cli agent stop {}

# Restart all running agents
ciris-cli agent list --status running --format json | \
  jq -r '.[].agent_id' | \
  xargs -I {} ciris-cli agent restart {}

# Backup all servers separately
for server in main scout; do
  ciris-cli config backup --server $server --output "backup-$server-$(date +%Y%m%d).json"
done
```

#### Check System Health

```bash
# Full system health check
ciris-cli system health
ciris-cli system status

# Check each server
for server in main scout; do
  echo "=== Server: $server ==="
  ciris-cli server stats $server
  ciris-cli server agents $server
done

# Inspect all agents
ciris-cli agent list --format json | \
  jq -r '.[].agent_id' | \
  xargs -I {} ciris-cli inspect agent {}
```

## Output Formats

### Table Format (Default)

```
AGENT ID              TEMPLATE    SERVER  STATUS   PORT
datum                 base        main    running  8001
scout-u7e9s3          scout       main    running  8007
echo-core-jm2jy2      echo-core   main    running  8003
```

### JSON Format

```json
[
  {
    "agent_id": "datum",
    "template": "base",
    "server_id": "main",
    "status": "running",
    "port": 8001
  }
]
```

### YAML Format

```yaml
- agent_id: datum
  template: base
  server_id: main
  status: running
  port: 8001
```

## Exit Codes

- `0` - Success
- `1` - General error
- `2` - Invalid arguments
- `3` - Authentication error
- `4` - API error
- `5` - Validation error
- `6` - Resource not found

## Environment Variables

- `CIRIS_MANAGER_API_URL` - API endpoint URL
- `CIRIS_MANAGER_TOKEN` - Authentication token
- `CIRIS_CLI_FORMAT` - Default output format (table, json, yaml)
- `CIRIS_CLI_VERBOSE` - Enable verbose mode (true/false)

## Troubleshooting

### Authentication Issues

```bash
# Check if token is valid
ciris-cli auth whoami

# Re-authenticate
ciris-cli auth login

# Use dev token (development mode)
ciris-cli auth token --dev
```

### Connection Issues

```bash
# Check API health
ciris-cli system health

# Test with verbose output
ciris-cli --verbose agent list

# Try different API endpoint
ciris-cli --api-url http://localhost:8888 agent list
```

### Inspection Failures

```bash
# Run with verbose logging
ciris-cli --verbose inspect agent datum

# Check specific components
ciris-cli inspect agent datum --check-labels
ciris-cli inspect agent datum --check-nginx
```

## Development

### Running from Source

```bash
# Install in development mode
pip install -e ".[dev]"

# Run CLI
ciris-cli --help

# Run tests
pytest tests/cli/
```

### Adding New Commands

See `ciris_manager/cli/commands/` for command implementations. Each command module should:

1. Import `CIRISManagerClient` from SDK
2. Use Pydantic models for validation
3. Support all output formats
4. Handle errors gracefully
5. Provide helpful error messages

## Support

For issues and questions:
- GitHub Issues: https://github.com/CIRISAI/CIRISManager/issues
- Documentation: https://github.com/CIRISAI/CIRISManager/docs
