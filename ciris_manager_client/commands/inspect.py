"""
Inspection and validation commands for CIRIS CLI.

These commands perform direct system checks (SSH, Docker, nginx) rather than
using the CIRISManager API. Used for debugging and validation.
"""

import json
import sys
import subprocess
from typing import Dict, Any, Optional, List, cast
from argparse import Namespace
from pathlib import Path

# Check paramiko availability without importing
import importlib.util  # noqa: E402

PARAMIKO_AVAILABLE = importlib.util.find_spec("paramiko") is not None

from ciris_manager.models.agent import AgentConfig  # noqa: E402


class InspectCommands:
    """Inspection and validation commands."""

    @staticmethod
    def agent(ctx: Any, args: Namespace) -> int:
        """
        Inspect agent (checks Docker labels, nginx routes, health).

        This performs direct system checks via SSH rather than using the API.
        Useful for debugging misconfigurations and verifying deployments.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - agent_id: Agent identifier
                - server: Server ID (default: "main")
                - check_labels: Only check Docker labels
                - check_nginx: Only check nginx routes
                - check_health: Only check health status

        Returns:
            0 on success, non-zero on failure
        """
        agent_id = args.agent_id
        server_id = getattr(args, "server", "main")

        # Determine which checks to run
        check_labels = getattr(args, "check_labels", False)
        check_nginx = getattr(args, "check_nginx", False)
        check_health = getattr(args, "check_health", False)

        # If no specific checks requested, run all
        run_all = not (check_labels or check_nginx or check_health)
        if run_all:
            check_labels = check_nginx = check_health = True

        if not ctx.quiet:
            print(f"\n=== Inspecting agent: {agent_id} (server: {server_id}) ===\n")

        results: Dict[str, Any] = {"agent_id": agent_id, "server_id": server_id, "checks": {}}

        # Check 1: Docker labels
        if check_labels:
            if not ctx.quiet:
                print("[1/3] Checking Docker labels...")

            try:
                labels = InspectCommands._check_docker_labels(agent_id, server_id, ctx.verbose)
                results["checks"]["docker_labels"] = {"status": "ok", "labels": labels}

                if not ctx.quiet:
                    if labels:
                        print("  ✓ Docker labels present:")
                        for key, value in labels.items():
                            if key.startswith("ai.ciris"):
                                print(f"    {key}: {value}")
                    else:
                        print("  ✗ No CIRIS labels found on container")
                        results["checks"]["docker_labels"]["status"] = "missing"

            except Exception as e:
                results["checks"]["docker_labels"] = {"status": "error", "error": str(e)}
                if not ctx.quiet:
                    print(f"  ✗ Error checking Docker labels: {e}")

        # Check 2: Nginx routes
        if check_nginx:
            if not ctx.quiet:
                print("\n[2/3] Checking nginx routes...")

            try:
                routes = InspectCommands._check_nginx_routes(agent_id, server_id, ctx.verbose)
                results["checks"]["nginx_routes"] = {"status": "ok", "routes": routes}

                if not ctx.quiet:
                    if routes:
                        print(f"  ✓ Found {len(routes)} nginx route(s):")
                        for route in routes:
                            print(f"    {route}")
                    else:
                        print("  ✗ No nginx routes found for agent")
                        results["checks"]["nginx_routes"]["status"] = "missing"

            except Exception as e:
                results["checks"]["nginx_routes"] = {"status": "error", "error": str(e)}
                if not ctx.quiet:
                    print(f"  ✗ Error checking nginx routes: {e}")

        # Check 3: Health status
        if check_health:
            if not ctx.quiet:
                print("\n[3/3] Checking health status...")

            try:
                health = InspectCommands._check_health_status(agent_id, ctx)
                results["checks"]["health"] = {"status": "ok", "health": health}

                if not ctx.quiet:
                    if health:
                        print("  ✓ Health status:")
                        print(f"    Status: {health.get('status', 'unknown')}")
                        print(f"    Cognitive State: {health.get('cognitive_state', 'unknown')}")
                        print(f"    Version: {health.get('version', 'unknown')}")
                    else:
                        print("  ✗ Could not retrieve health status")
                        results["checks"]["health"]["status"] = "unavailable"

            except Exception as e:
                results["checks"]["health"] = {"status": "error", "error": str(e)}
                if not ctx.quiet:
                    print(f"  ✗ Error checking health: {e}")

        # Summary
        if not ctx.quiet:
            print("\n=== Inspection Summary ===")
            all_ok = all(check.get("status") == "ok" for check in results["checks"].values())
            if all_ok:
                print("✓ All checks passed")
            else:
                print("✗ Some checks failed or had warnings")

        # Output results in requested format
        if ctx.output_format == "json":
            print(json.dumps(results, indent=2))
        elif ctx.output_format == "yaml":
            import yaml

            print(yaml.dump(results, default_flow_style=False))

        # Return exit code based on results
        all_ok = all(check.get("status") == "ok" for check in results["checks"].values())
        return 0 if all_ok else 1

    @staticmethod
    def _check_docker_labels(agent_id: str, server_id: str, verbose: bool) -> Dict[str, str]:
        """
        Check Docker labels for an agent container.

        Args:
            agent_id: Agent identifier
            server_id: Server ID
            verbose: Enable verbose output

        Returns:
            Dictionary of Docker labels
        """
        container_name = f"ciris-{agent_id}"

        if server_id == "main":
            # Local server - use docker directly
            cmd = ["docker", "inspect", container_name, "--format={{json .Config.Labels}}"]
        else:
            # Remote server - use SSH
            if not PARAMIKO_AVAILABLE:
                # Fall back to subprocess SSH
                ssh_key = Path.home() / ".ssh" / "ciris_deploy"
                if not ssh_key.exists():
                    raise RuntimeError("SSH key not found: ~/.ssh/ciris_deploy")

                # Get server hostname from config (simplified)
                # In production, this would load from manager config
                server_map = {"scout": "root@207.148.14.113"}
                ssh_target = server_map.get(server_id, f"root@{server_id}")

                cmd = [
                    "ssh",
                    "-i",
                    str(ssh_key),
                    ssh_target,
                    f"docker inspect {container_name} --format='{{{{json .Config.Labels}}}}'",
                ]
            else:
                # Use paramiko for better control
                raise NotImplementedError("Paramiko SSH support not yet implemented")

        if verbose:
            print(f"  Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Docker inspect failed: {result.stderr}")

        # Parse JSON output
        labels = json.loads(result.stdout.strip())
        return cast(Dict[str, str], labels)

    @staticmethod
    def _check_nginx_routes(agent_id: str, server_id: str, verbose: bool) -> List[str]:
        """
        Check nginx configuration for agent routes.

        Args:
            agent_id: Agent identifier
            server_id: Server ID
            verbose: Enable verbose output

        Returns:
            List of route patterns found
        """
        routes = []

        if server_id == "main":
            # Local server - check nginx config directly
            nginx_config_path = Path("/home/ciris/nginx/nginx.conf")
            if not nginx_config_path.exists():
                raise RuntimeError(f"Nginx config not found: {nginx_config_path}")

            with open(nginx_config_path) as f:
                config = f.read()
        else:
            # Remote server - SSH to read config
            ssh_key = Path.home() / ".ssh" / "ciris_deploy"
            if not ssh_key.exists():
                raise RuntimeError("SSH key not found: ~/.ssh/ciris_deploy")

            server_map = {"scout": "root@207.148.14.113"}
            ssh_target = server_map.get(server_id, f"root@{server_id}")

            cmd = ["ssh", "-i", str(ssh_key), ssh_target, "cat /home/ciris/nginx/nginx.conf"]

            if verbose:
                print(f"  Running: {' '.join(cmd)}")

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Could not read nginx config: {result.stderr}")

            config = result.stdout

        # Search for agent routes in config
        # Look for patterns like:
        # - location /api/agent_id/
        # - location /agent/agent_id/
        # - upstream agent_agent_id

        for line in config.split("\n"):
            line = line.strip()

            # API route
            if f"location /api/{agent_id}/" in line:
                routes.append(f"API: /api/{agent_id}/")

            # GUI route
            if f"location /agent/{agent_id}/" in line:
                routes.append(f"GUI: /agent/{agent_id}/")

            # Upstream definition
            if f"upstream agent_{agent_id.replace('-', '_')}" in line:
                routes.append(f"Upstream: agent_{agent_id.replace('-', '_')}")

        return routes

    @staticmethod
    def _check_health_status(agent_id: str, ctx: Any) -> Optional[Dict[str, Any]]:
        """
        Check agent health status via API.

        Args:
            agent_id: Agent identifier
            ctx: Command context with client

        Returns:
            Health status dictionary or None
        """
        try:
            agent_info = ctx.client.get_agent(agent_id)
            return {
                "status": agent_info.get("status"),
                "health": agent_info.get("health"),
                "cognitive_state": agent_info.get("cognitive_state"),
                "version": agent_info.get("version"),
                "codename": agent_info.get("codename"),
            }
        except Exception as e:
            if ctx.verbose:
                print(f"  Debug: API error: {e}")
            return None

    @staticmethod
    def server(ctx: Any, args: Namespace) -> int:
        """
        Inspect server configuration and agents.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - server_id: Server identifier

        Returns:
            0 on success, non-zero on failure
        """
        server_id = args.server_id

        if not ctx.quiet:
            print(f"\n=== Inspecting server: {server_id} ===\n")

        try:
            # Get all agents
            agents = ctx.client.list_agents()

            # Filter agents for this server
            server_agents = [a for a in agents if a.get("server_id") == server_id]

            results = {
                "server_id": server_id,
                "agent_count": len(server_agents),
                "agents": [
                    {
                        "agent_id": a.get("agent_id"),
                        "name": a.get("agent_name"),
                        "status": a.get("status"),
                        "port": a.get("api_port"),
                        "version": a.get("version"),
                    }
                    for a in server_agents
                ],
            }

            if not ctx.quiet:
                print(f"Server: {server_id}")
                print(f"Agents: {len(server_agents)}")
                print()
                for agent in server_agents:
                    status_icon = "✓" if agent.get("status") == "running" else "✗"
                    print(
                        f"  {status_icon} {agent.get('agent_id')} "
                        f"({agent.get('agent_name')}) - "
                        f"{agent.get('status')} - "
                        f"port {agent.get('api_port')}"
                    )

            # Output in requested format
            if ctx.output_format == "json":
                print(json.dumps(results, indent=2))
            elif ctx.output_format == "yaml":
                import yaml

                print(yaml.dump(results, default_flow_style=False))

            return 0

        except Exception as e:
            print(f"Error inspecting server: {e}", file=sys.stderr)
            return 1

    @staticmethod
    def validate(ctx: Any, args: Namespace) -> int:
        """
        Validate configuration file.

        Args:
            ctx: Command context
            args: Parsed arguments with:
                - file: Path to config file

        Returns:
            0 if valid, non-zero if invalid
        """
        file_path = Path(args.file)

        if not ctx.quiet:
            print(f"\n=== Validating config file: {file_path} ===\n")

        if not file_path.exists():
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            return 1

        try:
            # Load file
            with open(file_path) as f:
                if file_path.suffix in [".yaml", ".yml"]:
                    import yaml

                    data = yaml.safe_load(f)
                elif file_path.suffix == ".json":
                    data = json.load(f)
                else:
                    print(f"Error: Unsupported file format: {file_path.suffix}", file=sys.stderr)
                    return 1

            # Validate with Pydantic model
            config = AgentConfig(**data)

            if not ctx.quiet:
                print("✓ Configuration is valid")
                print(f"\nAgent ID: {config.agent_id}")
                print(f"Name: {config.name}")
                print(f"Template: {config.template}")
                print(f"Port: {config.port}")
                print(f"Environment variables: {len(config.environment)}")

            # Output in requested format
            if ctx.output_format == "json":
                print(json.dumps(config.model_dump(), indent=2))
            elif ctx.output_format == "yaml":
                import yaml

                print(yaml.dump(config.model_dump(), default_flow_style=False))

            return 0

        except Exception as e:
            print(f"✗ Validation failed: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return 1

    @staticmethod
    def system(ctx: Any, args: Namespace) -> int:
        """
        Full system inspection (all agents, all servers).

        Args:
            ctx: Command context
            args: Parsed arguments

        Returns:
            0 on success, non-zero on failure
        """
        if not ctx.quiet:
            print("\n=== System Inspection ===\n")

        try:
            # Get all agents
            agents = ctx.client.list_agents()

            # Group by server
            servers: Dict[str, List[Dict[str, Any]]] = {}
            for agent in agents:
                server_id = agent.get("server_id", "main")
                if server_id not in servers:
                    servers[server_id] = []
                servers[server_id].append(agent)

            # Create typed result structures
            servers_dict: Dict[str, Any] = {}
            summary_dict: Dict[str, int] = {"running": 0, "stopped": 0, "other": 0}

            results: Dict[str, Any] = {
                "total_agents": len(agents),
                "servers": servers_dict,
                "summary": summary_dict,
            }

            for server_id, server_agents in servers.items():
                server_info: Dict[str, Any] = {"agent_count": len(server_agents), "agents": []}
                servers_dict[server_id] = server_info

                if not ctx.quiet:
                    print(f"\nServer: {server_id}")
                    print(f"  Agents: {len(server_agents)}")

                for agent in server_agents:
                    status = agent.get("status", "unknown")
                    agent_summary = {
                        "agent_id": agent.get("agent_id"),
                        "name": agent.get("agent_name"),
                        "status": status,
                        "port": agent.get("api_port"),
                        "version": agent.get("version"),
                    }
                    server_info["agents"].append(agent_summary)

                    # Count statuses
                    if status == "running":
                        summary_dict["running"] += 1
                    elif status == "stopped":
                        summary_dict["stopped"] += 1
                    else:
                        summary_dict["other"] += 1

                    if not ctx.quiet:
                        status_icon = "✓" if status == "running" else "✗"
                        print(
                            f"    {status_icon} {agent.get('agent_id')} - "
                            f"{status} - port {agent.get('api_port')}"
                        )

            if not ctx.quiet:
                print("\n=== Summary ===")
                print(f"Total agents: {results['total_agents']}")
                print(f"  Running: {results['summary']['running']}")
                print(f"  Stopped: {results['summary']['stopped']}")
                print(f"  Other: {results['summary']['other']}")

            # Output in requested format
            if ctx.output_format == "json":
                print(json.dumps(results, indent=2))
            elif ctx.output_format == "yaml":
                import yaml

                print(yaml.dump(results, default_flow_style=False))

            return 0

        except Exception as e:
            print(f"Error inspecting system: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return 1
