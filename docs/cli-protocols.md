# CIRIS CLI Tool - Protocol Definitions

This document defines the protocols (interfaces) for all CLI modules to ensure consistent design and implementation.

## Architecture Overview

```
ciris-cli
├── main.py                      # Entry point, argument parsing, command routing
├── protocols.py                 # Protocol definitions (this document)
├── output.py                    # Output formatting (table, json, yaml)
├── utils.py                     # Common utilities (error handling, spinner, etc.)
└── commands/
    ├── agent.py                 # Agent management commands
    ├── config.py                # Configuration management commands
    ├── maintenance.py           # Maintenance mode commands
    ├── oauth.py                 # OAuth management commands
    ├── deploy.py                # Deployment operations commands
    ├── canary.py                # Canary deployment commands
    ├── template.py              # Template management commands
    ├── server.py                # Server management commands
    ├── system.py                # System operations commands
    ├── auth.py                  # Authentication commands
    └── inspect.py               # Inspection & validation commands
```

## Core Protocols

### 1. CommandContext Protocol

```python
from typing import Protocol, Optional
from ciris_manager.sdk import CIRISManagerClient

class CommandContext(Protocol):
    """Context passed to all commands with common resources."""

    client: CIRISManagerClient
    """API client instance"""

    output_format: str
    """Output format: 'table', 'json', or 'yaml'"""

    quiet: bool
    """Suppress non-essential output"""

    verbose: bool
    """Enable verbose logging"""
```

### 2. OutputFormatter Protocol

```python
from typing import Protocol, Any, List, Dict

class OutputFormatter(Protocol):
    """Protocol for output formatting."""

    def format_table(self, data: List[Dict[str, Any]], columns: List[str]) -> str:
        """Format data as a table."""
        ...

    def format_json(self, data: Any) -> str:
        """Format data as JSON."""
        ...

    def format_yaml(self, data: Any) -> str:
        """Format data as YAML."""
        ...

    def format_output(self, data: Any, format: str, columns: Optional[List[str]] = None) -> str:
        """Format output based on format string."""
        ...
```

### 3. CommandHandler Protocol

```python
from typing import Protocol
from argparse import Namespace

class CommandHandler(Protocol):
    """Protocol for command handlers."""

    def execute(self, ctx: CommandContext, args: Namespace) -> int:
        """
        Execute the command.

        Args:
            ctx: Command context with client and settings
            args: Parsed command-line arguments

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        ...
```

## Command Module Interfaces

### Agent Commands (`commands/agent.py`)

```python
class AgentCommands:
    """Agent lifecycle management commands."""

    @staticmethod
    def list(ctx: CommandContext, args: Namespace) -> int:
        """List agents with optional filtering."""
        # Supports: --server, --deployment, --status, --format
        ...

    @staticmethod
    def get(ctx: CommandContext, args: Namespace) -> int:
        """Get detailed agent information."""
        # Args: agent_id, --format
        ...

    @staticmethod
    def create(ctx: CommandContext, args: Namespace) -> int:
        """Create a new agent."""
        # Args: --name, --template, --server, --env (multiple),
        #       --use-mock-llm, --enable-discord, --billing-enabled, --billing-api-key
        ...

    @staticmethod
    def delete(ctx: CommandContext, args: Namespace) -> int:
        """Delete an agent."""
        # Args: agent_id, --force
        ...

    @staticmethod
    def start(ctx: CommandContext, args: Namespace) -> int:
        """Start an agent."""
        # Args: agent_id
        ...

    @staticmethod
    def stop(ctx: CommandContext, args: Namespace) -> int:
        """Stop an agent."""
        # Args: agent_id
        ...

    @staticmethod
    def restart(ctx: CommandContext, args: Namespace) -> int:
        """Restart an agent."""
        # Args: agent_id
        ...

    @staticmethod
    def shutdown(ctx: CommandContext, args: Namespace) -> int:
        """Gracefully shutdown an agent."""
        # Args: agent_id, --message
        ...

    @staticmethod
    def logs(ctx: CommandContext, args: Namespace) -> int:
        """View agent logs."""
        # Args: agent_id, --lines, --follow
        ...

    @staticmethod
    def versions(ctx: CommandContext, args: Namespace) -> int:
        """Show agent version information."""
        # Args: --agent-id (optional)
        ...
```

### Config Commands (`commands/config.py`)

```python
class ConfigCommands:
    """Configuration management commands."""

    @staticmethod
    def get(ctx: CommandContext, args: Namespace) -> int:
        """Get agent configuration."""
        # Args: agent_id, --format
        ...

    @staticmethod
    def update(ctx: CommandContext, args: Namespace) -> int:
        """Update agent configuration."""
        # Args: agent_id, --env (multiple), --from-file
        ...

    @staticmethod
    def export(ctx: CommandContext, args: Namespace) -> int:
        """Export agent configuration to file."""
        # Args: agent_id, --output, --format, --server (for all agents on server)
        ...

    @staticmethod
    def import_config(ctx: CommandContext, args: Namespace) -> int:
        """Import agent configuration from file."""
        # Args: file, --dry-run, --agent-id (override)
        ...

    @staticmethod
    def backup(ctx: CommandContext, args: Namespace) -> int:
        """Backup all agent configurations."""
        # Args: --output, --server (optional)
        ...

    @staticmethod
    def restore(ctx: CommandContext, args: Namespace) -> int:
        """Restore agent configurations from backup."""
        # Args: file, --agent-id (optional), --dry-run
        ...
```

### Maintenance Commands (`commands/maintenance.py`)

```python
class MaintenanceCommands:
    """Maintenance mode management commands."""

    @staticmethod
    def enter(ctx: CommandContext, args: Namespace) -> int:
        """Enter maintenance mode."""
        # Args: agent_id, --message
        ...

    @staticmethod
    def exit(ctx: CommandContext, args: Namespace) -> int:
        """Exit maintenance mode."""
        # Args: agent_id
        ...

    @staticmethod
    def status(ctx: CommandContext, args: Namespace) -> int:
        """Check maintenance status."""
        # Args: agent_id
        ...

    @staticmethod
    def list(ctx: CommandContext, args: Namespace) -> int:
        """List all agents in maintenance mode."""
        ...
```

### OAuth Commands (`commands/oauth.py`)

```python
class OAuthCommands:
    """OAuth management commands."""

    @staticmethod
    def verify(ctx: CommandContext, args: Namespace) -> int:
        """Verify OAuth status."""
        # Args: agent_id
        ...

    @staticmethod
    def complete(ctx: CommandContext, args: Namespace) -> int:
        """Complete OAuth flow."""
        # Args: agent_id, --code
        ...

    @staticmethod
    def status(ctx: CommandContext, args: Namespace) -> int:
        """Check OAuth status for all agents."""
        ...
```

### Deploy Commands (`commands/deploy.py`)

```python
class DeployCommands:
    """Deployment operations commands."""

    @staticmethod
    def notify(ctx: CommandContext, args: Namespace) -> int:
        """Notify agents about update."""
        # Args: --agent-image, --gui-image, --nginx-image, --strategy, --message
        ...

    @staticmethod
    def launch(ctx: CommandContext, args: Namespace) -> int:
        """Launch a pending deployment."""
        # Args: deployment_id
        ...

    @staticmethod
    def status(ctx: CommandContext, args: Namespace) -> int:
        """Get deployment status."""
        # Args: --deployment-id (optional), --follow
        ...

    @staticmethod
    def pending(ctx: CommandContext, args: Namespace) -> int:
        """List pending deployments."""
        # Args: --all
        ...

    @staticmethod
    def preview(ctx: CommandContext, args: Namespace) -> int:
        """Preview deployment."""
        # Args: deployment_id
        ...

    @staticmethod
    def events(ctx: CommandContext, args: Namespace) -> int:
        """Show deployment events."""
        # Args: deployment_id, --follow
        ...

    @staticmethod
    def cancel(ctx: CommandContext, args: Namespace) -> int:
        """Cancel deployment."""
        ...

    @staticmethod
    def reject(ctx: CommandContext, args: Namespace) -> int:
        """Reject deployment."""
        # Args: --reason
        ...

    @staticmethod
    def pause(ctx: CommandContext, args: Namespace) -> int:
        """Pause deployment."""
        ...

    @staticmethod
    def rollback(ctx: CommandContext, args: Namespace) -> int:
        """Rollback deployment."""
        ...

    @staticmethod
    def rollback_options(ctx: CommandContext, args: Namespace) -> int:
        """List rollback options."""
        ...

    @staticmethod
    def rollback_preview(ctx: CommandContext, args: Namespace) -> int:
        """Preview rollback."""
        # Args: deployment_id
        ...

    @staticmethod
    def approve_rollback(ctx: CommandContext, args: Namespace) -> int:
        """Approve rollback."""
        # Args: rollback_id
        ...

    @staticmethod
    def single(ctx: CommandContext, args: Namespace) -> int:
        """Deploy to single agent."""
        # Args: agent_id, --agent-image, --gui-image
        ...

    @staticmethod
    def history(ctx: CommandContext, args: Namespace) -> int:
        """View deployment history."""
        # Args: --limit
        ...

    @staticmethod
    def changelog(ctx: CommandContext, args: Namespace) -> int:
        """View changelog."""
        # Args: --version (optional)
        ...
```

### Canary Commands (`commands/canary.py`)

```python
class CanaryCommands:
    """Canary deployment commands."""

    @staticmethod
    def groups(ctx: CommandContext, args: Namespace) -> int:
        """List canary groups."""
        ...

    @staticmethod
    def set_group(ctx: CommandContext, args: Namespace) -> int:
        """Set agent canary group."""
        # Args: agent_id, --group (explorer|early_adopter|general)
        ...

    @staticmethod
    def adoption(ctx: CommandContext, args: Namespace) -> int:
        """View version adoption statistics."""
        # Args: --history
        ...
```

### Template Commands (`commands/template.py`)

```python
class TemplateCommands:
    """Template management commands."""

    @staticmethod
    def list(ctx: CommandContext, args: Namespace) -> int:
        """List available templates."""
        ...

    @staticmethod
    def details(ctx: CommandContext, args: Namespace) -> int:
        """Get template details."""
        # Args: template_name
        ...

    @staticmethod
    def env_default(ctx: CommandContext, args: Namespace) -> int:
        """View default environment for template."""
        # Args: template_name
        ...
```

### Server Commands (`commands/server.py`)

```python
class ServerCommands:
    """Server management commands."""

    @staticmethod
    def list(ctx: CommandContext, args: Namespace) -> int:
        """List all servers."""
        ...

    @staticmethod
    def get(ctx: CommandContext, args: Namespace) -> int:
        """Get server details."""
        # Args: server_id
        ...

    @staticmethod
    def stats(ctx: CommandContext, args: Namespace) -> int:
        """Get server statistics."""
        # Args: server_id
        ...

    @staticmethod
    def agents(ctx: CommandContext, args: Namespace) -> int:
        """List agents on server."""
        # Args: server_id
        ...

    @staticmethod
    def compare(ctx: CommandContext, args: Namespace) -> int:
        """Compare two servers."""
        # Args: server1_id, server2_id
        ...
```

### System Commands (`commands/system.py`)

```python
class SystemCommands:
    """System operations commands."""

    @staticmethod
    def health(ctx: CommandContext, args: Namespace) -> int:
        """Check system health."""
        ...

    @staticmethod
    def status(ctx: CommandContext, args: Namespace) -> int:
        """Get system status."""
        ...

    @staticmethod
    def ports(ctx: CommandContext, args: Namespace) -> int:
        """View allocated ports."""
        ...

    @staticmethod
    def tokens(ctx: CommandContext, args: Namespace) -> int:
        """View deployment tokens."""
        ...
```

### Auth Commands (`commands/auth.py`)

```python
class AuthCommands:
    """Authentication commands."""

    @staticmethod
    def login(ctx: CommandContext, args: Namespace) -> int:
        """OAuth login (opens browser)."""
        ...

    @staticmethod
    def logout(ctx: CommandContext, args: Namespace) -> int:
        """OAuth logout."""
        ...

    @staticmethod
    def whoami(ctx: CommandContext, args: Namespace) -> int:
        """Show current user."""
        ...

    @staticmethod
    def device(ctx: CommandContext, args: Namespace) -> int:
        """Device code flow for headless systems."""
        ...

    @staticmethod
    def token(ctx: CommandContext, args: Namespace) -> int:
        """Generate dev token (development mode only)."""
        # Args: --dev
        ...
```

### Inspect Commands (`commands/inspect.py`)

```python
class InspectCommands:
    """Inspection & validation commands (non-API operations)."""

    @staticmethod
    def agent(ctx: CommandContext, args: Namespace) -> int:
        """Inspect agent (Docker labels, nginx routes, health)."""
        # Args: agent_id, --server, --check-labels, --check-nginx, --check-health
        ...

    @staticmethod
    def server(ctx: CommandContext, args: Namespace) -> int:
        """Inspect server."""
        # Args: server_id
        ...

    @staticmethod
    def validate(ctx: CommandContext, args: Namespace) -> int:
        """Validate config file."""
        # Args: file
        ...

    @staticmethod
    def system(ctx: CommandContext, args: Namespace) -> int:
        """Full system inspection."""
        ...
```

## Utility Protocols

### Error Handling

```python
class CLIError(Exception):
    """Base class for CLI errors."""
    exit_code: int = 1

class AuthenticationError(CLIError):
    """Authentication failed."""
    exit_code: int = 3

class APIError(CLIError):
    """API request failed."""
    exit_code: int = 4

class ValidationError(CLIError):
    """Validation failed."""
    exit_code: int = 5

class NotFoundError(CLIError):
    """Resource not found."""
    exit_code: int = 6
```

### Progress Indicators

```python
class ProgressIndicator(Protocol):
    """Protocol for progress indicators."""

    def start(self, message: str) -> None:
        """Start showing progress."""
        ...

    def update(self, message: str) -> None:
        """Update progress message."""
        ...

    def stop(self, message: str) -> None:
        """Stop showing progress."""
        ...
```

## Implementation Guidelines

### 1. Error Handling

All commands must:
- Return 0 on success, non-zero on error
- Use try/except blocks to catch SDK exceptions
- Convert SDK exceptions to appropriate CLIError subclasses
- Print user-friendly error messages

```python
try:
    result = ctx.client.get_agent(agent_id)
    print(formatter.format_output(result, ctx.output_format))
    return 0
except AuthenticationError as e:
    print(f"Error: {e}", file=sys.stderr)
    return 3
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    return 1
```

### 2. Output Formatting

All commands must:
- Respect ctx.output_format (table, json, yaml)
- Use the OutputFormatter for consistent formatting
- Support quiet mode (suppress non-essential output)
- Support verbose mode (show detailed information)

```python
if not ctx.quiet:
    print(f"Fetching agent {agent_id}...")

result = ctx.client.get_agent(agent_id)

if ctx.output_format == 'table':
    columns = ['agent_id', 'status', 'port', 'version']
    print(formatter.format_table([result], columns))
elif ctx.output_format == 'json':
    print(formatter.format_json(result))
elif ctx.output_format == 'yaml':
    print(formatter.format_yaml(result))
```

### 3. Confirmation Prompts

Destructive operations must:
- Ask for confirmation unless --force is provided
- Show what will be affected
- Allow users to cancel

```python
if not args.force:
    agent = ctx.client.get_agent(agent_id)
    print(f"About to delete agent: {agent['agent_id']} ({agent['name']})")
    confirm = input("Are you sure? [y/N]: ")
    if confirm.lower() != 'y':
        print("Cancelled.")
        return 0

ctx.client.delete_agent(agent_id)
print(f"✓ Agent {agent_id} deleted successfully")
return 0
```

### 4. Progress Indicators

Long-running operations should show progress:

```python
with ProgressIndicator() as progress:
    progress.start("Creating agent...")
    result = ctx.client.create_agent(**kwargs)
    progress.update("Waiting for agent to start...")
    time.sleep(5)
    status = ctx.client.get_agent(result['agent_id'])
    progress.stop(f"✓ Agent {result['agent_id']} created successfully")
```

## Exit Codes

```python
EXIT_SUCCESS = 0           # Command succeeded
EXIT_ERROR = 1             # General error
EXIT_INVALID_ARGS = 2      # Invalid arguments
EXIT_AUTH_ERROR = 3        # Authentication error
EXIT_API_ERROR = 4         # API error
EXIT_VALIDATION_ERROR = 5  # Validation error
EXIT_NOT_FOUND = 6         # Resource not found
```

## Testing Protocol

Each command module must include:

1. **Unit tests** - Test command logic without API calls
2. **Integration tests** - Test with mock SDK client
3. **Example usage** - Document common use cases

```python
# test_agent_commands.py
def test_list_agents():
    """Test agent list command."""
    mock_client = MagicMock()
    mock_client.list_agents.return_value = [
        {"agent_id": "test", "status": "running"}
    ]

    ctx = CommandContext(
        client=mock_client,
        output_format="json",
        quiet=False,
        verbose=False
    )

    args = Namespace()
    exit_code = AgentCommands.list(ctx, args)

    assert exit_code == 0
    mock_client.list_agents.assert_called_once()
```

## Module Dependencies

```
commands/
├── agent.py       (depends on: sdk, models.agent, output)
├── config.py      (depends on: sdk, models.agent, models.backup, output)
├── maintenance.py (depends on: sdk, models.agent, output)
├── oauth.py       (depends on: sdk, models.agent, output)
├── deploy.py      (depends on: sdk, models.deployment, output)
├── canary.py      (depends on: sdk, models.deployment, output)
├── template.py    (depends on: sdk, models.template, output)
├── server.py      (depends on: sdk, models.server, output)
├── system.py      (depends on: sdk, models.system, output)
├── auth.py        (depends on: sdk, output)
└── inspect.py     (depends on: sdk, models.agent, paramiko, output)
```

## Implementation Order

**Phase 1: Core Infrastructure**
1. `protocols.py` - Protocol definitions
2. `output.py` - Output formatting
3. `utils.py` - Common utilities
4. `main.py` - Entry point and routing

**Phase 2: Essential Commands** (for immediate use)
1. `commands/agent.py` - list, get, create, delete
2. `commands/config.py` - get, export, import, backup, restore
3. `commands/inspect.py` - agent inspection

**Phase 3: Additional Commands**
4. `commands/maintenance.py`
5. `commands/oauth.py`
6. `commands/server.py`
7. `commands/template.py`
8. `commands/system.py`
9. `commands/auth.py`

**Phase 4: Advanced Commands**
10. `commands/deploy.py`
11. `commands/canary.py`

This protocol ensures consistent, maintainable, and user-friendly CLI commands across all modules.
