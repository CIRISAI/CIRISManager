#!/usr/bin/env python3
"""
CIRISManager CLI entry point.
"""

import argparse
import asyncio
import sys
import yaml
from pathlib import Path

from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.auth_cli import handle_auth_command
from ciris_manager.cli_client import add_cli_commands, handle_agent_commands, handle_system_commands
from ciris_manager.sdk import CIRISManagerClient


def generate_default_config(config_path: str) -> None:
    """Generate a default configuration file."""
    default_config = {
        "docker": {"compose_file": "/home/ciris/CIRISAgent/deployment/docker-compose.yml"},
        "watchdog": {"check_interval": 30, "crash_threshold": 3, "crash_window": 300},
        "container_management": {"interval": 300, "pull_images": True},
        "api": {"host": "127.0.0.1", "port": 8888},
    }

    Path(config_path).parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        yaml.dump(default_config, f, default_flow_style=False)

    print(f"Generated default configuration at: {config_path}")


async def run_manager(config_path: str) -> None:
    """Run the CIRISManager."""
    # Import and run the properly configured main function
    from ciris_manager.manager import main
    await main()


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CIRIS Container Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run the manager service
  ciris-manager --config /etc/ciris-manager/config.yml
  
  # Generate a default config
  ciris-manager --generate-config
  
  # Authenticate with the manager
  ciris-manager auth login your-email@ciris.ai
  
  # Get authentication token
  ciris-manager auth token
        """,
    )

    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Auth subcommand
    auth_parser = subparsers.add_parser("auth", help="Authentication management")
    auth_parser.add_argument(
        "--base-url",
        default="https://agents.ciris.ai",
        help="Base URL for CIRIS Manager (default: https://agents.ciris.ai)",
    )

    auth_subparsers = auth_parser.add_subparsers(dest="auth_command", help="Auth commands")

    # Auth login
    login_parser = auth_subparsers.add_parser("login", help="Login with Google OAuth")
    login_parser.add_argument("email", help="Your @ciris.ai email address")

    # Auth logout
    auth_subparsers.add_parser("logout", help="Remove saved authentication")

    # Auth status
    auth_subparsers.add_parser("status", help="Show authentication status")

    # Auth token
    auth_subparsers.add_parser("token", help="Print current token (for use in scripts)")

    # Add SDK-based CLI commands
    add_cli_commands(subparsers)

    # Original manager arguments (when no subcommand is used)
    parser.add_argument(
        "--config",
        default="/etc/ciris-manager/config.yml",
        help="Path to configuration file (default: /etc/ciris-manager/config.yml)",
    )
    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Generate a default configuration file and exit",
    )

    args = parser.parse_args()

    # Handle auth subcommand
    if args.command == "auth":
        if not args.auth_command:
            auth_parser.print_help()
            sys.exit(1)
        sys.exit(handle_auth_command(args))

    # Handle agent subcommand
    elif args.command == "agent":
        if not args.agent_command:
            parser.parse_args([args.command, "--help"])
            sys.exit(1)
        client = CIRISManagerClient(base_url=args.base_url)
        sys.exit(handle_agent_commands(client, args))

    # Handle system subcommand
    elif args.command == "system":
        if not args.system_command:
            parser.parse_args([args.command, "--help"])
            sys.exit(1)
        client = CIRISManagerClient(base_url=args.base_url)
        sys.exit(handle_system_commands(client, args))

    # Original manager behavior (when no subcommand)
    if args.generate_config:
        generate_default_config(args.config)
        sys.exit(0)

    # Check if config exists
    if not Path(args.config).exists():
        print(f"Configuration file not found: {args.config}")
        print(f"Generate one with: ciris-manager --generate-config --config {args.config}")
        sys.exit(1)

    # Run the manager
    try:
        asyncio.run(run_manager(args.config))
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()
