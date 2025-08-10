"""
Refactored CLI commands for CIRISManager using the SDK.
Reduces cyclomatic complexity by breaking down large functions.
"""
# mypy: ignore-errors

import json
import sys
from typing import Any, Dict, List, Optional
import argparse
from tabulate import tabulate

from .sdk import CIRISManagerClient, CIRISManagerError, AuthenticationError


def print_json(data: Any) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2))


def print_table(data: list, headers: list) -> None:
    """Print data as a table."""
    print(tabulate(data, headers=headers, tablefmt="grid"))


def parse_environment_vars(env_list: Optional[List[str]]) -> Dict[str, str]:
    """Parse environment variable list into dictionary."""
    env = {}
    if env_list:
        for e in env_list:
            key, value = e.split("=", 1)
            env[key] = value
    return env


def parse_mounts(mount_list: Optional[List[str]]) -> List[Dict[str, str]]:
    """Parse mount list into mount configuration."""
    mounts = []
    if mount_list:
        for m in mount_list:
            source, target = m.split(":", 1)
            mounts.append({"source": source, "target": target})
    return mounts


def handle_list_agents(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent list command."""
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


def handle_get_agent(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent get command."""
    agent = client.get_agent(args.agent_id)
    print_json(agent)
    return 0


def handle_create_agent(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent create command."""
    env = parse_environment_vars(args.env)
    mounts = parse_mounts(args.mount) if hasattr(args, "mount") else []

    result = client.create_agent(
        name=args.name,
        template=args.template,
        environment=env,
        mounts=mounts if mounts else None,
        use_mock_llm=args.mock_llm if hasattr(args, "mock_llm") else False,
        enable_discord=args.enable_discord if hasattr(args, "enable_discord") else False,
    )

    print(f"✅ Agent created: {result.get('agent_id', 'unknown')}")
    if args.json:
        print_json(result)
    return 0


def handle_update_agent(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent update command."""
    config = {}
    if hasattr(args, "disable_mock_llm") and args.disable_mock_llm:
        config["environment"] = {"CIRIS_MOCK_LLM": "false"}
    if hasattr(args, "enable_production") and args.enable_production:
        config["environment"] = {"CIRIS_MOCK_LLM": "false"}

    result = client.update_agent_config(args.agent_id, config)
    print(f"✅ Agent configuration updated: {args.agent_id}")
    if args.json:
        print_json(result)
    return 0


def handle_delete_agent(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent delete command."""
    if not args.yes:
        response = input(f"Are you sure you want to delete agent '{args.agent_id}'? (y/N): ")
        if response.lower() != "y":
            print("Cancelled")
            return 1

    result = client.delete_agent(args.agent_id)
    print(f"✅ Agent deleted: {args.agent_id}")
    if args.json:
        print_json(result)
    return 0


def handle_start_agent(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent start command."""
    result = client.start_agent(args.agent_id)
    print(f"✅ Agent started: {args.agent_id}")
    if args.json:
        print_json(result)
    return 0


def handle_stop_agent(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent stop command."""
    result = client.stop_agent(args.agent_id)
    print(f"✅ Agent stopped: {args.agent_id}")
    if args.json:
        print_json(result)
    return 0


def handle_restart_agent(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent restart command."""
    result = client.restart_agent(args.agent_id)
    print(f"✅ Agent restarted: {args.agent_id}")
    if args.json:
        print_json(result)
    return 0


def handle_agent_logs(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent logs command."""
    logs = client.get_agent_logs(args.agent_id, lines=args.lines)
    print(logs)
    return 0


# Command dispatcher mapping
AGENT_COMMAND_HANDLERS = {
    "list": handle_list_agents,
    "get": handle_get_agent,
    "create": handle_create_agent,
    "update": handle_update_agent,
    "delete": handle_delete_agent,
    "start": handle_start_agent,
    "stop": handle_stop_agent,
    "restart": handle_restart_agent,
    "logs": handle_agent_logs,
}


def handle_agent_commands(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle agent-related commands with reduced complexity."""
    try:
        handler = AGENT_COMMAND_HANDLERS.get(args.agent_command)
        if handler:
            return handler(client, args)
        else:
            print(f"Unknown agent command: {args.agent_command}", file=sys.stderr)
            return 1

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


# System command handlers
def handle_status(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle system status command."""
    status = client.get_status()
    print_json(status)
    return 0


def handle_health(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle system health command."""
    health = client.get_health()
    print_json(health)
    return 0


def handle_metrics(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle system metrics command."""
    metrics = client.get_metrics()
    print_json(metrics)
    return 0


def handle_templates(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle templates list command."""
    templates = client.list_templates()
    if args.json if hasattr(args, "json") else False:
        print_json(templates)
    else:
        table_data = []
        for template in templates:
            table_data.append(
                [
                    template.get("name", "N/A"),
                    template.get("description", "N/A")[:60],
                    "✓" if template.get("approved", False) else "",
                ]
            )
        print_table(table_data, ["Template", "Description", "Approved"])
    return 0


def handle_update_status(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle update status command."""
    status = client.get_update_status()
    print_json(status)
    return 0


def handle_notify_update(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle update notification command."""
    if not args.yes:
        response = input("Are you sure you want to notify agents of an update? (y/N): ")
        if response.lower() != "y":
            print("Cancelled")
            return 1

    result = client.notify_update(
        agent_image=args.agent_image,
        gui_image=args.gui_image,
        message=args.message,
        strategy=args.strategy,
    )
    print(f"✅ Update notification sent: {result.get('deployment_id', 'unknown')}")
    if args.json:
        print_json(result)
    return 0


def handle_ping(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle ping command."""
    result = client.ping()
    print(f"✅ Manager is responding: {result}")
    return 0


# System command dispatcher
SYSTEM_COMMAND_HANDLERS = {
    "status": handle_status,
    "health": handle_health,
    "metrics": handle_metrics,
    "templates": handle_templates,
    "update-status": handle_update_status,
    "notify-update": handle_notify_update,
    "ping": handle_ping,
}


def handle_system_commands(client: CIRISManagerClient, args: argparse.Namespace) -> int:
    """Handle system-related commands with reduced complexity."""
    try:
        handler = SYSTEM_COMMAND_HANDLERS.get(args.system_command)
        if handler:
            return handler(client, args)
        else:
            print(f"Unknown system command: {args.system_command}", file=sys.stderr)
            return 1

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
    """Add CLI commands to argument parser subparsers."""

    # Agent commands
    agent_parser = subparsers.add_parser("agent", help="Agent management")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", help="Agent commands")

    # Agent list
    list_parser = agent_subparsers.add_parser("list", help="List all agents")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Agent get
    get_parser = agent_subparsers.add_parser("get", help="Get agent details")
    get_parser.add_argument("agent_id", help="Agent ID")

    # Agent create
    create_parser = agent_subparsers.add_parser("create", help="Create a new agent")
    create_parser.add_argument("--name", required=True, help="Agent name")
    create_parser.add_argument("--template", required=True, help="Template name")
    create_parser.add_argument("--env", action="append", help="Environment variables (KEY=VALUE)")
    create_parser.add_argument("--mount", action="append", help="Volume mounts (SOURCE:TARGET)")
    create_parser.add_argument("--mock-llm", action="store_true", help="Use mock LLM")
    create_parser.add_argument("--enable-discord", action="store_true", help="Enable Discord")
    create_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Agent update
    update_parser = agent_subparsers.add_parser("update", help="Update agent configuration")
    update_parser.add_argument("agent_id", help="Agent ID")
    update_parser.add_argument("--disable-mock-llm", action="store_true", help="Disable mock LLM")
    update_parser.add_argument(
        "--enable-production", action="store_true", help="Enable production mode"
    )
    update_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Agent delete
    delete_parser = agent_subparsers.add_parser("delete", help="Delete an agent")
    delete_parser.add_argument("agent_id", help="Agent ID")
    delete_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    delete_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Agent start/stop/restart
    for cmd in ["start", "stop", "restart"]:
        cmd_parser = agent_subparsers.add_parser(cmd, help=f"{cmd.capitalize()} an agent")
        cmd_parser.add_argument("agent_id", help="Agent ID")
        cmd_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Agent logs
    logs_parser = agent_subparsers.add_parser("logs", help="Get agent logs")
    logs_parser.add_argument("agent_id", help="Agent ID")
    logs_parser.add_argument("--lines", type=int, default=100, help="Number of lines")

    # System commands
    system_parser = subparsers.add_parser("system", help="System management")
    system_subparsers = system_parser.add_subparsers(dest="system_command", help="System commands")

    # Simple system commands
    for cmd in ["status", "health", "metrics", "templates", "update-status", "ping"]:
        system_subparsers.add_parser(cmd, help=f"Get system {cmd}")

    # Notify update
    notify_parser = system_subparsers.add_parser("notify-update", help="Notify agents of update")
    notify_parser.add_argument("--agent-image", required=True, help="Agent image")
    notify_parser.add_argument("--gui-image", required=True, help="GUI image")
    notify_parser.add_argument("--message", help="Update message")
    notify_parser.add_argument("--strategy", choices=["canary", "immediate"], default="canary")
    notify_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    notify_parser.add_argument("--json", action="store_true", help="Output as JSON")
