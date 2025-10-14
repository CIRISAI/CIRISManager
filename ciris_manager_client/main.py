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
from typing import Optional, cast

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
    2. ~/.manager_token file

    Returns:
        Token string if found, None otherwise
    """
    # Try environment variable first
    token = os.environ.get("CIRIS_MANAGER_TOKEN")
    if token:
        return token

    # Try token file
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

    if not token:
        print(
            "Error: No authentication token found.\n"
            "Please set CIRIS_MANAGER_TOKEN environment variable or create ~/.manager_token file.",
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
