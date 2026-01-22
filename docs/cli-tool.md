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

# The CLI will be available as 'ciris-manager-client'
ciris-manager-client --help
```

## Configuration

The CLI looks for authentication tokens in the following locations (in order):

1. `~/.manager_token` - Simple token file
2. `~/.config/ciris-manager/token.json` - Token with expiry
3. Environment variable `CIRIS_MANAGER_TOKEN`

API endpoint defaults to `https://agents.ciris.ai` but can be overridden:

```bash
# Set custom API endpoint
ciris-manager-client --api-url http://localhost:8888 agent list

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
ciris-manager-client agent list

# List agents on specific server
ciris-manager-client agent list --server scout

# List agents by deployment
ciris-manager-client agent list --deployment CIRIS_DISCORD_PILOT

# List agents by status
ciris-manager-client agent list --status running

# Output as JSON
ciris-manager-client agent list --format json

# Filter and format
ciris-manager-client agent list --server main --status running --format table
```

#### Get Agent Details

```bash
# Get detailed information about an agent
ciris-manager-client agent get datum

# Output as JSON for scripting
ciris-manager-client agent get datum --format json
```

#### Create Agent

```bash
# Create basic agent
ciris-manager-client agent create --name my-agent --template scout

# Create on specific server
ciris-manager-client agent create --name scout-test --template scout --server scout

# Create with environment variables
ciris-manager-client agent create \
  --name my-agent \
  --template scout \
  --env OAUTH_CALLBACK_BASE_URL=https://scoutapi.ciris.ai \
  --env CUSTOM_VAR=value

# Create with mock LLM
ciris-manager-client agent create --name test-agent --template scout --use-mock-llm

# Create with Discord enabled
ciris-manager-client agent create --name discord-bot --template scout --enable-discord

# Create with billing
ciris-manager-client agent create \
  --name paid-agent \
  --template scout \
  --billing-enabled \
  --billing-api-key sk_test_xxx
```

#### Delete Agent

```bash
# Delete agent (with confirmation)
ciris-manager-client agent delete scout-test-abc123

# Force delete without confirmation
ciris-manager-client agent delete scout-test-abc123 --force
```

#### Start/Stop/Restart Agent

```bash
# Start agent
ciris-manager-client agent start datum

# Stop agent
ciris-manager-client agent stop datum

# Restart agent
ciris-manager-client agent restart datum

# Graceful shutdown (allows agent to finish work)
ciris-manager-client agent shutdown datum --message "Maintenance window"
```

#### View Agent Logs

```bash
# View last 100 lines
ciris-manager-client agent logs datum

# View last N lines
ciris-manager-client agent logs datum --lines 500

# Follow logs (like tail -f)
ciris-manager-client agent logs datum --follow

# Save to file
ciris-manager-client agent logs datum --lines 1000 > datum.log
```

#### Agent Version Information

```bash
# Show version info for all agents
ciris-manager-client agent versions

# Show version for specific agent
ciris-manager-client agent versions --agent-id datum
```

#### Agent Access Details

Get connection details for an agent including service token, API endpoint, and database info:

```bash
# Get access details for an agent
ciris-manager-client agent access datum

# Get access for agent on specific server
ciris-manager-client agent access scout-remote-test-dahrb9 --server-id scout1

# Get access for specific occurrence
ciris-manager-client agent access scout-remote-test-dahrb9 --occurrence-id 002 --server-id scout2
```

Output includes:
- Agent ID and registry key
- Server ID and port
- API endpoint URL
- Decrypted service token
- Database location (host and container paths)
- Server hostname and VPC IP

### Adapter Management

Manage adapters on agents (load, unload, list):

```bash
# List adapters on an agent
ciris-manager-client adapter list datum

# Load an adapter
ciris-manager-client adapter load datum ciris_covenant_metrics

# Load adapter with custom config
ciris-manager-client adapter load datum my_adapter --config '{"key": "value"}'

# Load adapter without persistence (won't survive restart)
ciris-manager-client adapter load datum my_adapter --no-persist

# Unload an adapter
ciris-manager-client adapter unload datum ciris_covenant_metrics_abc123

# Get adapter details
ciris-manager-client adapter get datum ciris_covenant_metrics_abc123
```

### Configuration Management

#### Get Agent Configuration

```bash
# Get agent config
ciris-manager-client config get datum

# Get as JSON
ciris-manager-client config get datum --format json

# Get as YAML
ciris-manager-client config get datum --format yaml
```

#### Update Agent Configuration

```bash
# Update environment variable
ciris-manager-client config update datum --env NEW_VAR=value

# Update multiple environment variables
ciris-manager-client config update datum \
  --env VAR1=value1 \
  --env VAR2=value2

# Update from JSON file
ciris-manager-client config update datum --from-file config.json
```

#### Export Configuration

```bash
# Export to JSON file
ciris-manager-client config export datum --output datum-config.json

# Export to YAML
ciris-manager-client config export datum --output datum-config.yaml --format yaml

# Export all agents on a server
ciris-manager-client config export --server scout --output scout-agents.json
```

#### Import Configuration

```bash
# Import from file (dry run first)
ciris-manager-client config import datum-config.json --dry-run

# Import and create/update agent
ciris-manager-client config import datum-config.json

# Import with different agent ID
ciris-manager-client config import datum-config.json --agent-id new-datum
```

#### Backup All Configurations

```bash
# Backup all agents
ciris-manager-client config backup --output agents-backup.json

# Backup specific server
ciris-manager-client config backup --server main --output main-backup.json

# Backup with timestamp
ciris-manager-client config backup --output "backup-$(date +%Y%m%d).json"
```

#### Restore from Backup

```bash
# Restore all agents from backup
ciris-manager-client config restore agents-backup.json

# Restore specific agent from backup
ciris-manager-client config restore agents-backup.json --agent-id datum

# Restore with dry run
ciris-manager-client config restore agents-backup.json --dry-run
```

### Maintenance Mode

```bash
# Enter maintenance mode
ciris-manager-client maintenance enter datum --message "Database migration"

# Exit maintenance mode
ciris-manager-client maintenance exit datum

# Check maintenance status
ciris-manager-client maintenance status datum

# List all agents in maintenance
ciris-manager-client maintenance list
```

### OAuth Management

```bash
# Verify OAuth status
ciris-manager-client oauth verify datum

# Complete OAuth flow
ciris-manager-client oauth complete datum --code AUTH_CODE

# Check OAuth for all agents
ciris-manager-client oauth status
```

### Deployment Operations

#### Notify About Update

```bash
# Notify agents about new version (canary deployment)
ciris-manager-client deploy notify \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.0.0 \
  --gui-image ghcr.io/cirisai/ciris-gui:v2.0.0 \
  --strategy canary \
  --message "Security update with new features"

# Immediate deployment (all agents at once)
ciris-manager-client deploy notify \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.0.1 \
  --strategy immediate \
  --message "Critical security patch"
```

#### Launch Deployment

```bash
# Launch a pending deployment
ciris-manager-client deploy launch DEPLOYMENT_ID
```

#### Deployment Status

```bash
# Get current deployment status
ciris-manager-client deploy status

# Get specific deployment status
ciris-manager-client deploy status --deployment-id abc123

# Watch deployment progress
ciris-manager-client deploy status --follow
```

#### Pending Deployments

```bash
# List pending deployments for current agent
ciris-manager-client deploy pending

# List all pending deployments
ciris-manager-client deploy pending --all
```

#### Preview Deployment

```bash
# Preview what will happen
ciris-manager-client deploy preview DEPLOYMENT_ID
```

#### Deployment Events

```bash
# Show deployment events/timeline
ciris-manager-client deploy events DEPLOYMENT_ID

# Follow events in real-time
ciris-manager-client deploy events DEPLOYMENT_ID --follow
```

#### Control Deployment

```bash
# Cancel deployment
ciris-manager-client deploy cancel

# Reject deployment
ciris-manager-client deploy reject --reason "Failed smoke tests"

# Pause deployment
ciris-manager-client deploy pause
```

#### Rollback

```bash
# Rollback current deployment
ciris-manager-client deploy rollback

# List rollback options
ciris-manager-client deploy rollback-options

# Preview rollback
ciris-manager-client deploy rollback-preview DEPLOYMENT_ID

# Approve pending rollback
ciris-manager-client deploy approve-rollback ROLLBACK_ID
```

#### Single Agent Deploy

```bash
# Deploy to single agent
ciris-manager-client deploy single datum \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.0.0
```

#### Deployment History

```bash
# View deployment history
ciris-manager-client deploy history

# View last N deployments
ciris-manager-client deploy history --limit 10

# View history as JSON
ciris-manager-client deploy history --format json
```

#### View Changelog

```bash
# View latest changelog
ciris-manager-client deploy changelog

# View specific version changelog
ciris-manager-client deploy changelog --version v2.0.0
```

### Canary Deployments

```bash
# List canary groups
ciris-manager-client canary groups

# Set agent canary group
ciris-manager-client canary set-group datum --group explorer

# Available groups: explorer, early_adopter, general

# View version adoption statistics
ciris-manager-client canary adoption

# View adoption over time
ciris-manager-client canary adoption --history
```

### Template Management

```bash
# List available templates
ciris-manager-client template list

# Get template details
ciris-manager-client template details scout

# View default environment for template
ciris-manager-client template env-default scout
```

### Server Management

```bash
# List all servers
ciris-manager-client server list

# Get server details
ciris-manager-client server get main

# Get server statistics
ciris-manager-client server stats scout

# List agents on server
ciris-manager-client server agents scout

# Compare servers
ciris-manager-client server compare main scout
```

### System Operations

```bash
# Health check
ciris-manager-client system health

# Detailed status
ciris-manager-client system status

# View allocated ports
ciris-manager-client system ports

# View deployment tokens
ciris-manager-client system tokens
```

### Authentication

```bash
# OAuth login (opens browser)
ciris-manager-client auth login

# OAuth logout
ciris-manager-client auth logout

# Show current user
ciris-manager-client auth whoami

# Device code flow (for headless systems)
ciris-manager-client auth device

# Generate dev token (development mode only)
ciris-manager-client auth token --dev
```

### Inspection & Validation

These commands perform deeper inspection beyond API calls, including SSH checks.

```bash
# Inspect agent (checks Docker labels, nginx routes, health)
ciris-manager-client inspect agent datum

# Inspect remote agent
ciris-manager-client inspect agent scout-u7e9s3 --server scout

# Check specific aspects
ciris-manager-client inspect agent datum --check-labels
ciris-manager-client inspect agent datum --check-nginx
ciris-manager-client inspect agent datum --check-health

# Inspect server
ciris-manager-client inspect server scout

# Validate config file
ciris-manager-client inspect validate config.json

# Full system inspection
ciris-manager-client inspect system
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
ciris-manager-client agent create \
  --name production-scout \
  --template scout \
  --server scout \
  --env OAUTH_CALLBACK_BASE_URL=https://scoutapi.ciris.ai

# 2. Verify it's working
ciris-manager-client inspect agent scout-xxx --server scout

# 3. Check logs
ciris-manager-client agent logs scout-xxx
```

#### Backup and Recreate Agent

```bash
# 1. Export existing agent config
ciris-manager-client config export scout-remote-test-dahrb9 --output scout-backup.json

# 2. Delete old agent
ciris-manager-client agent delete scout-remote-test-dahrb9 --force

# 3. Recreate from backup
ciris-manager-client config import scout-backup.json

# 4. Verify new agent
ciris-manager-client inspect agent <new-agent-id> --check-labels --check-nginx
```

#### Migrate Agent Between Servers

```bash
# 1. Export config from main server
ciris-manager-client config export datum --output datum-main.json

# 2. Edit config to change server_id
# Edit datum-main.json: "server_id": "scout"

# 3. Create on new server
ciris-manager-client config import datum-main.json --agent-id datum-scout

# 4. Test new agent
ciris-manager-client inspect agent datum-scout --server scout

# 5. Delete old agent if satisfied
ciris-manager-client agent delete datum --force
```

#### Rolling Deployment

```bash
# 1. Notify about new version
ciris-manager-client deploy notify \
  --agent-image ghcr.io/cirisai/ciris-agent:v2.1.0 \
  --strategy canary \
  --message "New features: X, Y, Z"

# 2. Monitor deployment progress
ciris-manager-client deploy status --follow

# 3. Check events
ciris-manager-client deploy events <deployment-id>

# 4. If issues, rollback
ciris-manager-client deploy rollback
```

#### Maintenance Window

```bash
# 1. Put agents in maintenance mode
ciris-manager-client maintenance enter datum --message "Database upgrade"
ciris-manager-client maintenance enter scout-u7e9s3 --message "Database upgrade"

# 2. Perform maintenance
# ... database operations ...

# 3. Take agents out of maintenance
ciris-manager-client maintenance exit datum
ciris-manager-client maintenance exit scout-u7e9s3

# 4. Verify health
ciris-manager-client inspect agent datum
ciris-manager-client inspect agent scout-u7e9s3
```

#### Batch Operations with Shell

```bash
# Stop all agents on scout server
ciris-manager-client agent list --server scout --format json | \
  jq -r '.[].agent_id' | \
  xargs -I {} ciris-manager-client agent stop {}

# Restart all running agents
ciris-manager-client agent list --status running --format json | \
  jq -r '.[].agent_id' | \
  xargs -I {} ciris-manager-client agent restart {}

# Backup all servers separately
for server in main scout; do
  ciris-manager-client config backup --server $server --output "backup-$server-$(date +%Y%m%d).json"
done
```

#### Check System Health

```bash
# Full system health check
ciris-manager-client system health
ciris-manager-client system status

# Check each server
for server in main scout; do
  echo "=== Server: $server ==="
  ciris-manager-client server stats $server
  ciris-manager-client server agents $server
done

# Inspect all agents
ciris-manager-client agent list --format json | \
  jq -r '.[].agent_id' | \
  xargs -I {} ciris-manager-client inspect agent {}
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
ciris-manager-client auth whoami

# Re-authenticate
ciris-manager-client auth login

# Use dev token (development mode)
ciris-manager-client auth token --dev
```

### Connection Issues

```bash
# Check API health
ciris-manager-client system health

# Test with verbose output
ciris-manager-client --verbose agent list

# Try different API endpoint
ciris-manager-client --api-url http://localhost:8888 agent list
```

### Inspection Failures

```bash
# Run with verbose logging
ciris-manager-client --verbose inspect agent datum

# Check specific components
ciris-manager-client inspect agent datum --check-labels
ciris-manager-client inspect agent datum --check-nginx
```

## Development

### Running from Source

```bash
# Install in development mode
pip install -e ".[dev]"

# Run CLI
ciris-manager-client --help

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
