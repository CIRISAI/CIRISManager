#!/usr/bin/env python3
"""
CIRIS CLI Tool - Main entry point.

This module provides the main CLI interface for interacting with CIRISManager.
It uses argparse for command-line argument parsing and routes commands to
appropriate command handlers.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, cast

from ciris_manager_sdk import CIRISManagerClient, AuthenticationError, APIError


# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_INVALID_ARGS = 2
EXIT_AUTH_ERROR = 3
EXIT_API_ERROR = 4
EXIT_VALIDATION_ERROR = 5
EXIT_NOT_FOUND = 6


class CLIError(Exception):
    """Base class for CLI errors."""

    exit_code: int = EXIT_ERROR


class CLIAuthenticationError(CLIError):
    """Authentication failed."""

    exit_code: int = EXIT_AUTH_ERROR


class CLIAPIError(CLIError):
    """API request failed."""

    exit_code: int = EXIT_API_ERROR


class ValidationError(CLIError):
    """Validation failed."""

    exit_code: int = EXIT_VALIDATION_ERROR


class NotFoundError(CLIError):
    """Resource not found."""

    exit_code: int = EXIT_NOT_FOUND


class CommandContext:
    """Context passed to all commands with common resources."""

    def __init__(
        self,
        client: CIRISManagerClient,
        output_format: str = "table",
        quiet: bool = False,
        verbose: bool = False,
    ):
        self.client = client
        self.output_format = output_format
        self.quiet = quiet
        self.verbose = verbose


def load_token() -> Optional[str]:
    """
    Load authentication token from environment or file.

    Tries in order:
    1. CIRIS_MANAGER_TOKEN environment variable
    2. ~/.config/ciris-manager/token.json (device flow token)
    3. ~/.manager_token file (legacy)

    Returns:
        Token string if found, None otherwise
    """
    import json
    from datetime import datetime

    # Try environment variable first
    token = os.environ.get("CIRIS_MANAGER_TOKEN")
    if token:
        return token

    # Try device flow token file
    device_token_file = Path.home() / ".config" / "ciris-manager" / "token.json"
    if device_token_file.exists():
        try:
            with open(device_token_file) as f:
                data: Dict[str, Any] = json.load(f)
            # Check expiry
            expires_at = datetime.fromisoformat(data["expires_at"])
            if datetime.utcnow() < expires_at:
                token_value = data.get("token")
                return cast(Optional[str], token_value)
        except Exception:
            pass

    # Try legacy token file
    token_file = Path.home() / ".manager_token"
    if token_file.exists():
        try:
            return token_file.read_text().strip()
        except Exception:
            pass

    return None


def get_api_url() -> str:
    """
    Get API URL from environment or use default.

    Returns:
        API URL string
    """
    return os.environ.get("CIRIS_MANAGER_API_URL", "https://agents.ciris.ai")


def setup_agent_parser(subparsers):
    """Set up agent command subparser."""
    agent_parser = subparsers.add_parser(
        "agent", help="Agent lifecycle management", description="Manage CIRIS agents"
    )
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", help="Agent commands")

    # agent list
    list_parser = agent_subparsers.add_parser("list", help="List agents")
    list_parser.add_argument("--server", help="Filter by server ID")
    list_parser.add_argument("--deployment", help="Filter by deployment ID")
    list_parser.add_argument("--status", help="Filter by status")

    # agent get
    get_parser = agent_subparsers.add_parser("get", help="Get agent details")
    get_parser.add_argument("agent_id", help="Agent ID")

    # agent create
    create_parser = agent_subparsers.add_parser("create", help="Create a new agent")
    create_parser.add_argument("--name", required=True, help="Agent name")
    create_parser.add_argument("--template", default="basic", help="Template to use")
    create_parser.add_argument("--server", help="Target server ID")
    create_parser.add_argument(
        "--occurrence-id", help="Occurrence ID for multi-instance agents (e.g., '002', '003')"
    )
    create_parser.add_argument(
        "--env", action="append", help="Environment variable (KEY=VALUE)", metavar="KEY=VALUE"
    )
    create_parser.add_argument("--env-file", help="JSON file with environment variables")
    create_parser.add_argument("--use-mock-llm", action="store_true", help="Use mock LLM")
    create_parser.add_argument(
        "--enable-discord", action="store_true", help="Enable Discord adapter"
    )
    create_parser.add_argument("--billing-enabled", action="store_true", help="Enable billing")
    create_parser.add_argument("--billing-api-key", help="Billing API key")

    # agent delete
    delete_parser = agent_subparsers.add_parser("delete", help="Delete an agent")
    delete_parser.add_argument("agent_id", help="Agent ID")
    delete_parser.add_argument("--force", action="store_true", help="Skip confirmation")

    # agent start
    start_parser = agent_subparsers.add_parser("start", help="Start an agent")
    start_parser.add_argument("agent_id", help="Agent ID")

    # agent stop
    stop_parser = agent_subparsers.add_parser("stop", help="Stop an agent")
    stop_parser.add_argument("agent_id", help="Agent ID")

    # agent restart
    restart_parser = agent_subparsers.add_parser("restart", help="Restart an agent")
    restart_parser.add_argument("agent_id", help="Agent ID")

    # agent shutdown
    shutdown_parser = agent_subparsers.add_parser("shutdown", help="Gracefully shutdown an agent")
    shutdown_parser.add_argument("agent_id", help="Agent ID")
    shutdown_parser.add_argument("--message", help="Shutdown message")

    # agent logs
    logs_parser = agent_subparsers.add_parser("logs", help="View agent logs")
    logs_parser.add_argument("agent_id", help="Agent ID")
    logs_parser.add_argument("--lines", type=int, default=100, help="Number of lines to show")
    logs_parser.add_argument("--follow", action="store_true", help="Follow log output")

    # agent versions
    versions_parser = agent_subparsers.add_parser("versions", help="Show version information")
    versions_parser.add_argument("--agent-id", help="Specific agent ID (optional)")

    # agent deploy
    deploy_parser = agent_subparsers.add_parser("deploy", help="Deploy specific version to agent")
    deploy_parser.add_argument("agent_id", help="Agent ID")
    deploy_parser.add_argument(
        "--version", required=True, help="Version to deploy (e.g., 1.3.3 or latest)"
    )
    deploy_parser.add_argument("--message", default="CLI deployment", help="Deployment message")
    deploy_parser.add_argument(
        "--strategy",
        choices=["manual", "immediate", "docker"],
        default="docker",
        help="Deployment strategy (manual=consensual, immediate=API shutdown, docker=force restart)",
    )
    deploy_parser.add_argument(
        "--occurrence-id",
        help="Occurrence ID for multi-instance agents (e.g., '003', '002')",
    )
    deploy_parser.add_argument(
        "--server-id",
        help="Server ID for multi-server agents (e.g., 'main', 'scout', 'scout2')",
    )

    # agent maintenance
    maintenance_parser = agent_subparsers.add_parser(
        "maintenance", help="Get or set maintenance mode for an agent"
    )
    maintenance_parser.add_argument("agent_id", help="Agent ID")
    maintenance_parser.add_argument(
        "--enable",
        action="store_true",
        help="Enable maintenance mode (skip deployments and auto-restart)",
    )
    maintenance_parser.add_argument(
        "--disable", action="store_true", help="Disable maintenance mode (resume normal operations)"
    )

    # agent pull-logs
    pull_logs_parser = agent_subparsers.add_parser(
        "pull-logs", help="Download log files from agents"
    )
    pull_logs_parser.add_argument(
        "--agent-id", help="Specific agent ID (optional, pulls all if not specified)"
    )
    pull_logs_parser.add_argument(
        "--output-dir", "-o", help="Output directory (default: /tmp/agent_logs_TIMESTAMP)"
    )


def setup_config_parser(subparsers):
    """Set up config command subparser."""
    config_parser = subparsers.add_parser(
        "config", help="Configuration management", description="Manage agent configurations"
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_command", help="Configuration commands"
    )

    # config get
    get_parser = config_subparsers.add_parser("get", help="Get agent configuration")
    get_parser.add_argument("agent_id", help="Agent ID")

    # config update
    update_parser = config_subparsers.add_parser("update", help="Update agent configuration")
    update_parser.add_argument("agent_id", help="Agent ID")
    update_parser.add_argument(
        "--env", action="append", help="Environment variable (KEY=VALUE)", metavar="KEY=VALUE"
    )
    update_parser.add_argument("--from-file", help="Load config from file")

    # config export
    export_parser = config_subparsers.add_parser("export", help="Export configuration to file")
    export_parser.add_argument("agent_id", help="Agent ID")
    export_parser.add_argument("--output", required=True, help="Output file path")
    export_parser.add_argument("--server", help="Export all agents on server")

    # config import
    import_parser = config_subparsers.add_parser("import", help="Import configuration from file")
    import_parser.add_argument("file", help="Input file path")
    import_parser.add_argument("--dry-run", action="store_true", help="Dry run (no changes)")
    import_parser.add_argument("--agent-id", help="Override agent ID")

    # config backup
    backup_parser = config_subparsers.add_parser("backup", help="Backup all configurations")
    backup_parser.add_argument("--output", required=True, help="Output file path")
    backup_parser.add_argument("--server", help="Backup specific server")

    # config restore
    restore_parser = config_subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("file", help="Backup file path")
    restore_parser.add_argument("--agent-id", help="Restore specific agent")
    restore_parser.add_argument("--dry-run", action="store_true", help="Dry run (no changes)")


def setup_inspect_parser(subparsers):
    """Set up inspect command subparser."""
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspection & validation", description="Inspect and validate resources"
    )
    inspect_subparsers = inspect_parser.add_subparsers(
        dest="inspect_command", help="Inspection commands"
    )

    # inspect agent
    agent_parser = inspect_subparsers.add_parser("agent", help="Inspect agent")
    agent_parser.add_argument("agent_id", help="Agent ID")
    agent_parser.add_argument("--server", help="Server ID")
    agent_parser.add_argument("--check-labels", action="store_true", help="Check Docker labels")
    agent_parser.add_argument("--check-nginx", action="store_true", help="Check nginx routes")
    agent_parser.add_argument("--check-health", action="store_true", help="Check health status")

    # inspect server
    server_parser = inspect_subparsers.add_parser("server", help="Inspect server")
    server_parser.add_argument("server_id", help="Server ID")

    # inspect validate
    validate_parser = inspect_subparsers.add_parser("validate", help="Validate config file")
    validate_parser.add_argument("file", help="Config file path")

    # inspect system
    inspect_subparsers.add_parser("system", help="Full system inspection")


def setup_deployment_parser(subparsers):
    """Set up deployment command subparser."""
    deployment_parser = subparsers.add_parser(
        "deployment",
        help="Deployment management",
        description="Manage CD deployments and rollouts",
    )
    deployment_subparsers = deployment_parser.add_subparsers(
        dest="deployment_command", help="Deployment commands"
    )

    # deployment status
    status_parser = deployment_subparsers.add_parser("status", help="Get deployment status")
    status_parser.add_argument("--deployment-id", help="Specific deployment ID (optional)")

    # deployment cancel
    cancel_parser = deployment_subparsers.add_parser("cancel", help="Cancel a deployment")
    cancel_parser.add_argument("deployment_id", help="Deployment ID to cancel")
    cancel_parser.add_argument(
        "--reason", default="Cancelled via CLI", help="Reason for cancellation"
    )

    # deployment start
    start_parser = deployment_subparsers.add_parser("start", help="Start a pending deployment")
    start_parser.add_argument("deployment_id", help="Deployment ID to start")

    # deployment watch
    watch_parser = deployment_subparsers.add_parser(
        "watch",
        help="Watch deployment events in real-time",
        description="Stream deployment events via SSE and exit on completion/failure",
    )
    watch_parser.add_argument("deployment_id", help="Deployment ID to watch")

    # deployment retry
    retry_parser = deployment_subparsers.add_parser(
        "retry",
        help="Retry a failed deployment",
        description="Create a new deployment from a failed/cancelled deployment's original notification",
    )
    retry_parser.add_argument("deployment_id", help="Failed deployment ID to retry")
    retry_parser.add_argument(
        "--start", action="store_true", help="Automatically start the new deployment"
    )


def setup_auth_parser(subparsers):
    """Set up auth command subparser."""
    auth_parser = subparsers.add_parser(
        "auth",
        help="Authentication management",
        description="Manage CLI authentication with CIRIS Manager",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", help="Auth commands")

    # auth login
    login_parser = auth_subparsers.add_parser("login", help="Login with Google OAuth")
    login_parser.add_argument("email", nargs="?", help="Your @ciris.ai email address")

    # auth logout
    auth_subparsers.add_parser("logout", help="Remove saved credentials")

    # auth status
    auth_subparsers.add_parser("status", help="Show authentication status")

    # auth token
    auth_subparsers.add_parser("token", help="Print current token (for scripting)")


def setup_adapter_parser(subparsers):
    """Set up adapter command subparser."""
    adapter_parser = subparsers.add_parser(
        "adapter",
        help="Adapter management",
        description="Manage adapters on CIRIS agents",
    )
    adapter_subparsers = adapter_parser.add_subparsers(
        dest="adapter_command", help="Adapter commands"
    )

    # adapter list
    list_parser = adapter_subparsers.add_parser(
        "list", help="List all available adapters with their status"
    )
    list_parser.add_argument("agent_id", help="Agent ID")

    # adapter types
    types_parser = adapter_subparsers.add_parser(
        "types", help="List available adapter types on an agent"
    )
    types_parser.add_argument("agent_id", help="Agent ID")

    # adapter get
    get_parser = adapter_subparsers.add_parser("get", help="Get status of a specific adapter")
    get_parser.add_argument("agent_id", help="Agent ID")
    get_parser.add_argument("adapter_id", help="Adapter ID")

    # adapter manifest
    manifest_parser = adapter_subparsers.add_parser(
        "manifest", help="Get full manifest for an adapter type"
    )
    manifest_parser.add_argument("agent_id", help="Agent ID")
    manifest_parser.add_argument("adapter_type", help="Adapter type")

    # adapter load
    load_parser = adapter_subparsers.add_parser("load", help="Load/create an adapter on an agent")
    load_parser.add_argument("agent_id", help="Agent ID")
    load_parser.add_argument("adapter_type", help="Adapter type to load")
    load_parser.add_argument("--config-file", help="JSON file with adapter configuration")
    load_parser.add_argument("--adapter-id", help="Custom adapter ID")
    load_parser.add_argument(
        "--no-auto-start", action="store_true", help="Don't start adapter immediately"
    )

    # adapter unload
    unload_parser = adapter_subparsers.add_parser(
        "unload", help="Unload/stop an adapter on an agent"
    )
    unload_parser.add_argument("agent_id", help="Agent ID")
    unload_parser.add_argument("adapter_id", help="Adapter ID to unload")

    # adapter reload
    reload_parser = adapter_subparsers.add_parser(
        "reload", help="Reload an adapter with new configuration"
    )
    reload_parser.add_argument("agent_id", help="Agent ID")
    reload_parser.add_argument("adapter_id", help="Adapter ID to reload")
    reload_parser.add_argument("--config-file", help="JSON file with new configuration")
    reload_parser.add_argument(
        "--no-auto-start", action="store_true", help="Don't start adapter after reload"
    )

    # adapter configs
    configs_parser = adapter_subparsers.add_parser(
        "configs", help="Get all persisted adapter configurations"
    )
    configs_parser.add_argument("agent_id", help="Agent ID")

    # adapter remove-config
    remove_config_parser = adapter_subparsers.add_parser(
        "remove-config", help="Remove adapter configuration from registry"
    )
    remove_config_parser.add_argument("agent_id", help="Agent ID")
    remove_config_parser.add_argument("adapter_type", help="Adapter type")
    remove_config_parser.add_argument("--force", action="store_true", help="Skip confirmation")

    # adapter wizard-start
    wizard_start_parser = adapter_subparsers.add_parser(
        "wizard-start", help="Start a configuration wizard for an adapter"
    )
    wizard_start_parser.add_argument("agent_id", help="Agent ID")
    wizard_start_parser.add_argument("adapter_type", help="Adapter type to configure")
    wizard_start_parser.add_argument("--resume", help="Session ID to resume")

    # adapter wizard-step
    wizard_step_parser = adapter_subparsers.add_parser("wizard-step", help="Execute a wizard step")
    wizard_step_parser.add_argument("agent_id", help="Agent ID")
    wizard_step_parser.add_argument("adapter_type", help="Adapter type")
    wizard_step_parser.add_argument("session_id", help="Wizard session ID")
    wizard_step_parser.add_argument("step_id", help="Step ID to execute")
    wizard_step_parser.add_argument(
        "--data", action="append", help="Step data (KEY=VALUE)", metavar="KEY=VALUE"
    )
    wizard_step_parser.add_argument("--data-file", help="JSON file with step data")
    wizard_step_parser.add_argument(
        "--skip", action="store_true", help="Skip this step (if optional)"
    )

    # adapter wizard-complete
    wizard_complete_parser = adapter_subparsers.add_parser(
        "wizard-complete", help="Complete the wizard and apply configuration"
    )
    wizard_complete_parser.add_argument("agent_id", help="Agent ID")
    wizard_complete_parser.add_argument("adapter_type", help="Adapter type")
    wizard_complete_parser.add_argument("session_id", help="Wizard session ID")
    wizard_complete_parser.add_argument(
        "--no-confirm", action="store_true", help="Don't require confirmation"
    )


def setup_debug_parser(subparsers):
    """Set up debug command subparser."""
    debug_parser = subparsers.add_parser(
        "debug",
        help="Debug agent persistence",
        description="Query agent databases for debugging (tasks, thoughts, actions)",
    )
    debug_subparsers = debug_parser.add_subparsers(dest="debug_command", help="Debug commands")

    # Common arguments for all debug commands
    def add_common_args(parser):
        parser.add_argument("--server", help="Server ID for multi-server deployments")
        parser.add_argument("--occurrence", help="Occurrence ID for multi-instance agents")

    # debug tasks
    tasks_parser = debug_subparsers.add_parser("tasks", help="List tasks for an agent")
    tasks_parser.add_argument("agent_id", help="Agent ID")
    tasks_parser.add_argument(
        "--status", help="Filter by status (pending, active, completed, deferred)"
    )
    tasks_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum tasks to return (default: 50)"
    )
    add_common_args(tasks_parser)

    # debug task
    task_parser = debug_subparsers.add_parser("task", help="Get detailed task information")
    task_parser.add_argument("agent_id", help="Agent ID")
    task_parser.add_argument("task_id", help="Task ID")
    add_common_args(task_parser)

    # debug thoughts
    thoughts_parser = debug_subparsers.add_parser("thoughts", help="List thoughts for an agent")
    thoughts_parser.add_argument("agent_id", help="Agent ID")
    thoughts_parser.add_argument("--status", help="Filter by status")
    thoughts_parser.add_argument("--task-id", dest="task_id", help="Filter by task ID")
    thoughts_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum thoughts to return (default: 50)"
    )
    add_common_args(thoughts_parser)

    # debug thought
    thought_parser = debug_subparsers.add_parser("thought", help="Get detailed thought information")
    thought_parser.add_argument("agent_id", help="Agent ID")
    thought_parser.add_argument("thought_id", help="Thought ID (can be partial prefix)")
    add_common_args(thought_parser)

    # debug query
    query_parser = debug_subparsers.add_parser("query", help="Execute custom SQL query (read-only)")
    query_parser.add_argument("agent_id", help="Agent ID")
    query_parser.add_argument("query", help="SQL SELECT query to execute")
    add_common_args(query_parser)

    # debug schema
    schema_parser = debug_subparsers.add_parser("schema", help="Get database schema")
    schema_parser.add_argument("agent_id", help="Agent ID")
    add_common_args(schema_parser)


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog="ciris",
        description="CIRIS CLI - Manage CIRIS agents and infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all agents
  ciris agent list

  # Get agent details
  ciris agent get datum

  # Create a new agent
  ciris agent create --name myagent --template basic

  # View agent logs
  ciris agent logs datum --lines 50

  # Get agent configuration
  ciris config get datum

  # Export configuration
  ciris config export datum --output datum-config.json

  # Inspect agent
  ciris inspect agent datum --check-health

Environment Variables:
  CIRIS_MANAGER_API_URL  API URL (default: https://agents.ciris.ai)
  CIRIS_MANAGER_TOKEN    Authentication token

Token File:
  ~/.manager_token       Token file location
        """,
    )

    # Global arguments
    parser.add_argument(
        "--api-url",
        default=None,
        help="API URL (default: from env or https://agents.ciris.ai)",
    )
    parser.add_argument(
        "--token", default=None, help="Authentication token (default: from env or ~/.manager_token)"
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "yaml"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress non-essential output")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Set up command subparsers
    setup_agent_parser(subparsers)
    setup_config_parser(subparsers)
    setup_inspect_parser(subparsers)
    setup_deployment_parser(subparsers)
    setup_auth_parser(subparsers)
    setup_adapter_parser(subparsers)
    setup_debug_parser(subparsers)

    return parser


def route_command(ctx: CommandContext, args: argparse.Namespace) -> int:
    """
    Route command to appropriate handler.

    Args:
        ctx: Command context
        args: Parsed arguments

    Returns:
        Exit code
    """
    # Lazy import command modules to avoid circular dependencies
    try:
        if args.command == "agent":
            from ciris_manager_client.commands.agent import AgentCommands

            if not args.agent_command:
                print("Error: No agent subcommand specified", file=sys.stderr)
                return EXIT_INVALID_ARGS

            handler = getattr(AgentCommands, args.agent_command.replace("-", "_"), None)
            if handler:
                return cast(int, handler(ctx, args))
            else:
                print(f"Error: Unknown agent command: {args.agent_command}", file=sys.stderr)
                return EXIT_INVALID_ARGS

        elif args.command == "config":
            from ciris_manager_client.commands.config import ConfigCommands

            if not args.config_command:
                print("Error: No config subcommand specified", file=sys.stderr)
                return EXIT_INVALID_ARGS

            handler = getattr(ConfigCommands, args.config_command.replace("-", "_"), None)
            if handler:
                return cast(int, handler(ctx, args))
            else:
                print(f"Error: Unknown config command: {args.config_command}", file=sys.stderr)
                return EXIT_INVALID_ARGS

        elif args.command == "inspect":
            from ciris_manager_client.commands.inspect import InspectCommands

            if not args.inspect_command:
                print("Error: No inspect subcommand specified", file=sys.stderr)
                return EXIT_INVALID_ARGS

            handler = getattr(InspectCommands, args.inspect_command.replace("-", "_"), None)
            if handler:
                return cast(int, handler(ctx, args))
            else:
                print(f"Error: Unknown inspect command: {args.inspect_command}", file=sys.stderr)
                return EXIT_INVALID_ARGS

        elif args.command == "deployment":
            from ciris_manager_client.commands.deployment import DeploymentCommands

            if not args.deployment_command:
                print("Error: No deployment subcommand specified", file=sys.stderr)
                return EXIT_INVALID_ARGS

            handler = getattr(DeploymentCommands, args.deployment_command.replace("-", "_"), None)
            if handler:
                return cast(int, handler(ctx, args))
            else:
                print(
                    f"Error: Unknown deployment command: {args.deployment_command}", file=sys.stderr
                )
                return EXIT_INVALID_ARGS

        elif args.command == "auth":
            # Auth command is handled specially - doesn't need existing token
            from ciris_manager.auth_cli import handle_auth_command

            if not args.auth_command:
                print("Error: No auth subcommand specified", file=sys.stderr)
                print("Available commands: login, logout, status, token", file=sys.stderr)
                return EXIT_INVALID_ARGS

            # Create a namespace with base_url for auth handler
            args.base_url = ctx.client.base_url if ctx.client else get_api_url()
            return handle_auth_command(args)

        elif args.command == "adapter":
            from ciris_manager_client.commands.adapter import AdapterCommands

            if not args.adapter_command:
                print("Error: No adapter subcommand specified", file=sys.stderr)
                print(
                    "Available commands: list, types, get, manifest, load, unload, reload, "
                    "configs, remove-config, wizard-start, wizard-step, wizard-complete",
                    file=sys.stderr,
                )
                return EXIT_INVALID_ARGS

            handler = getattr(AdapterCommands, args.adapter_command.replace("-", "_"), None)
            if handler:
                return cast(int, handler(ctx, args))
            else:
                print(f"Error: Unknown adapter command: {args.adapter_command}", file=sys.stderr)
                return EXIT_INVALID_ARGS

        elif args.command == "debug":
            from ciris_manager_client.commands.debug import DebugCommands

            if not args.debug_command:
                print("Error: No debug subcommand specified", file=sys.stderr)
                print(
                    "Available commands: tasks, task, thoughts, thought, query, schema",
                    file=sys.stderr,
                )
                return EXIT_INVALID_ARGS

            handler = getattr(DebugCommands, args.debug_command.replace("-", "_"), None)
            if handler:
                return cast(int, handler(ctx, args))
            else:
                print(f"Error: Unknown debug command: {args.debug_command}", file=sys.stderr)
                return EXIT_INVALID_ARGS

        else:
            print(f"Error: Unknown command: {args.command}", file=sys.stderr)
            return EXIT_INVALID_ARGS

    except ImportError as e:
        print(f"Error: Command module not yet implemented: {e}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as e:
        if ctx.verbose:
            import traceback

            traceback.print_exc()
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_ERROR


def main() -> int:
    """
    Main CLI entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Parse arguments
    parser = create_parser()
    args = parser.parse_args()

    # Show help if no command specified
    if not args.command:
        parser.print_help()
        return EXIT_SUCCESS

    # Load token and API URL
    token = args.token or load_token()
    api_url = args.api_url or get_api_url()

    # Auth command doesn't require existing token
    if args.command == "auth":
        from ciris_manager.auth_cli import handle_auth_command

        if not args.auth_command:
            print("Error: No auth subcommand specified", file=sys.stderr)
            print("Available commands: login, logout, status, token", file=sys.stderr)
            return EXIT_INVALID_ARGS

        args.base_url = api_url
        return handle_auth_command(args)

    if not token:
        print(
            "Error: No authentication token found.\n"
            "Run 'ciris-manager-client auth login your-email@ciris.ai' to authenticate,\n"
            "or set CIRIS_MANAGER_TOKEN environment variable.",
            file=sys.stderr,
        )
        return EXIT_AUTH_ERROR

    # Create client
    try:
        client = CIRISManagerClient(base_url=api_url, token=token)
    except Exception as e:
        print(f"Error creating client: {e}", file=sys.stderr)
        return EXIT_ERROR

    # Create context
    ctx = CommandContext(
        client=client, output_format=args.format, quiet=args.quiet, verbose=args.verbose
    )

    # Route to command handler
    try:
        return route_command(ctx, args)
    except CLIAuthenticationError as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        return e.exit_code
    except CLIAPIError as e:
        print(f"API error: {e}", file=sys.stderr)
        return e.exit_code
    except ValidationError as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return e.exit_code
    except NotFoundError as e:
        print(f"Not found: {e}", file=sys.stderr)
        return e.exit_code
    except CLIError as e:
        print(f"Error: {e}", file=sys.stderr)
        return e.exit_code
    except AuthenticationError as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        return EXIT_AUTH_ERROR
    except APIError as e:
        print(f"API error: {e}", file=sys.stderr)
        return EXIT_API_ERROR
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return EXIT_ERROR
    except Exception as e:
        if args.verbose:
            import traceback

            traceback.print_exc()
        print(f"Unexpected error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
