"""
CLI commands for CIRISManager using the SDK.
"""
# mypy: ignore-errors

import json
import sys
from typing import Any
import argparse
from tabulate import tabulate

from .sdk import CIRISManagerClient, CIRISManagerError, AuthenticationError


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2))


def print_table(data: list, headers: list) -> None:
    """Print data as a table."""
    print(tabulate(data, headers=headers, tablefmt="grid"))


def handle_agent_commands(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent-related commands."""
    try:
        if args.agent_command == "list":
            agents = client.list_agents()
            if args.json:
                print_json(agents)
            else:
                table_data = []
                for agent in agents:
                    table_data.append(
                        [
                            agent.get("agent_id", "N/A"),
                            agent.get("agent_name", "N/A"),
                            agent.get("status", "N/A"),
                            agent.get("api_port", "N/A"),
                            agent.get("container_name", "N/A")[:30],
                        ]
                    )
                print_table(table_data, ["ID", "Name", "Status", "Port", "Container"])
            return 0

        elif args.agent_command == "get":
            agent = client.get_agent(args.agent_id)
            print_json(agent)
            return 0

        elif args.agent_command == "create":
            # Parse environment variables
            env = {}
            if args.env:
                for e in args.env:
                    key, value = e.split("=", 1)
                    env[key] = value

            # Parse mounts
            mounts = []
            if args.mount:
                for m in args.mount:
                    source, target = m.split(":", 1)
                    mounts.append({"source": source, "target": target})

            result = client.create_agent(
                name=args.name,
                template=args.template,
                environment=env,
                mounts=mounts if mounts else None,
            )
            print(f"✅ Agent created: {result.get('agent_id', 'unknown')}")
            if args.json:
                print_json(result)
            return 0

        elif args.agent_command == "delete":
            if not args.yes:
                response = input(
                    f"Are you sure you want to delete agent '{args.agent_id}'? (y/N): "
                )
                if response.lower() != "y":
                    print("Cancelled")
                    return 1

            result = client.delete_agent(args.agent_id)
            print(f"✅ Agent deleted: {args.agent_id}")
            if args.json:
                print_json(result)
            return 0

        elif args.agent_command == "start":
            result = client.start_agent(args.agent_id)
            print(f"✅ Agent started: {args.agent_id}")
            if args.json:
                print_json(result)
            return 0

        elif args.agent_command == "stop":
            result = client.stop_agent(args.agent_id)
            print(f"✅ Agent stopped: {args.agent_id}")
            if args.json:
                print_json(result)
            return 0

        elif args.agent_command == "restart":
            result = client.restart_agent(args.agent_id)
            print(f"✅ Agent restarted: {args.agent_id}")
            if args.json:
                print_json(result)
            return 0

        elif args.agent_command == "logs":
            logs = client.get_agent_logs(args.agent_id, lines=args.lines)
            print(logs)
            return 0

    except AuthenticationError as e:
        print(f"❌ Authentication error: {e}", file=sys.stderr)
        print("Please run: ciris-manager auth login your-email@ciris.ai", file=sys.stderr)
        return 1
    except CIRISManagerError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 1


def handle_system_commands(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle system-related commands."""
    try:
        if args.system_command == "status":
            status = client.get_status()
            print_json(status)
            return 0

        elif args.system_command == "health":
            health = client.get_health()
            if health.get("status") == "healthy":
                print("✅ Manager is healthy")
            else:
                print("⚠️ Manager health check failed")
            if args.json:
                print_json(health)
            return 0

        elif args.system_command == "metrics":
            metrics = client.get_metrics()
            print_json(metrics)
            return 0

        elif args.system_command == "templates":
            templates = client.list_templates()
            if args.json:
                print_json(templates)
            else:
                print("Available templates:")
                for template in templates:
                    print(f"  - {template}")
            return 0

    except AuthenticationError as e:
        print(f"❌ Authentication error: {e}", file=sys.stderr)
        print("Please run: ciris-manager auth login your-email@ciris.ai", file=sys.stderr)
        return 1
    except CIRISManagerError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        return 1


def add_cli_commands(subparsers: argparse._SubParsersAction) -> None:
    """Add CLI client commands to the main parser."""

    # Agent management commands
    agent_parser = subparsers.add_parser("agent", help="Agent management")
    agent_parser.add_argument(
        "--base-url",
        default="https://agents.ciris.ai",
        help="Base URL for CIRIS Manager (default: https://agents.ciris.ai)",
    )
    agent_parser.add_argument("--json", action="store_true", help="Output in JSON format")

    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", help="Agent commands")

    # List agents
    agent_subparsers.add_parser("list", help="List all agents")

    # Get agent
    get_parser = agent_subparsers.add_parser("get", help="Get agent details")
    get_parser.add_argument("agent_id", help="Agent ID")

    # Create agent
    create_parser = agent_subparsers.add_parser("create", help="Create a new agent")
    create_parser.add_argument("name", help="Agent name")
    create_parser.add_argument(
        "--template", default="basic", help="Template to use (default: basic)"
    )
    create_parser.add_argument("--env", action="append", help="Environment variable (KEY=VALUE)")
    create_parser.add_argument("--mount", action="append", help="Volume mount (SOURCE:TARGET)")

    # Delete agent
    delete_parser = agent_subparsers.add_parser("delete", help="Delete an agent")
    delete_parser.add_argument("agent_id", help="Agent ID")
    delete_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # Start agent
    start_parser = agent_subparsers.add_parser("start", help="Start an agent")
    start_parser.add_argument("agent_id", help="Agent ID")

    # Stop agent
    stop_parser = agent_subparsers.add_parser("stop", help="Stop an agent")
    stop_parser.add_argument("agent_id", help="Agent ID")

    # Restart agent
    restart_parser = agent_subparsers.add_parser("restart", help="Restart an agent")
    restart_parser.add_argument("agent_id", help="Agent ID")

    # Get logs
    logs_parser = agent_subparsers.add_parser("logs", help="Get agent logs")
    logs_parser.add_argument("agent_id", help="Agent ID")
    logs_parser.add_argument(
        "--lines", type=int, default=100, help="Number of lines (default: 100)"
    )

    # System commands
    system_parser = subparsers.add_parser("system", help="System information")
    system_parser.add_argument(
        "--base-url",
        default="https://agents.ciris.ai",
        help="Base URL for CIRIS Manager (default: https://agents.ciris.ai)",
    )
    system_parser.add_argument("--json", action="store_true", help="Output in JSON format")

    system_subparsers = system_parser.add_subparsers(dest="system_command", help="System commands")

    system_subparsers.add_parser("status", help="Get manager status")
    system_subparsers.add_parser("health", help="Check manager health")
    system_subparsers.add_parser("metrics", help="Get system metrics")
    system_subparsers.add_parser("templates", help="List available templates")
