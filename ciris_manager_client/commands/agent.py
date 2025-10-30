"""
Agent lifecycle management commands for CIRIS CLI.

This module provides commands for managing CIRIS agents including
creation, deletion, lifecycle operations, and monitoring.
"""

import sys
from argparse import Namespace
from typing import Dict, Any

from ciris_manager_sdk import APIError, AuthenticationError
from ciris_manager_client.protocols import (
    CommandContext,
    EXIT_SUCCESS,
    EXIT_ERROR,
    EXIT_AUTH_ERROR,
    EXIT_API_ERROR,
    EXIT_NOT_FOUND,
)
from ciris_manager_client.output import formatter


class AgentCommands:
    """Agent lifecycle management commands."""

    @staticmethod
    def list(ctx: CommandContext, args: Namespace) -> int:
        """
        List agents with optional filtering.

        Args:
            ctx: Command context
            args: Parsed arguments (server, deployment, status, format)

        Returns:
            Exit code
        """
        try:
            if not ctx.quiet:
                print("Fetching agents...")

            # Get all agents
            agents = ctx.client.list_agents()

            # Apply filters if provided
            if hasattr(args, "server") and args.server:
                agents = [a for a in agents if a.get("server_id") == args.server]

            if hasattr(args, "deployment") and args.deployment:
                agents = [a for a in agents if a.get("deployment") == args.deployment]

            if hasattr(args, "status") and args.status:
                agents = [a for a in agents if a.get("status") == args.status]

            if not agents:
                if not ctx.quiet:
                    print("No agents found")
                return EXIT_SUCCESS

            # Define columns for table view
            columns = [
                "agent_id",
                "agent_name",
                "status",
                "health",
                "api_port",
                "version",
                "template",
            ]

            # Format and print output
            output = formatter.format_output(agents, ctx.output_format, columns)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error listing agents: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def get(ctx: CommandContext, args: Namespace) -> int:
        """
        Get detailed agent information.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, format)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Fetching agent '{agent_id}'...")

            agent = ctx.client.get_agent(agent_id)

            # Format and print output
            output = formatter.format_output(agent, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error getting agent: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def create(ctx: CommandContext, args: Namespace) -> int:
        """
        Create a new agent.

        Args:
            ctx: Command context
            args: Parsed arguments (name, template, env, env_file, server, etc.)

        Returns:
            Exit code
        """
        try:
            # Build environment dict from --env-file if provided
            environment = {}
            file_server_id = None

            if hasattr(args, "env_file") and args.env_file:
                import json

                try:
                    with open(args.env_file, "r") as f:
                        file_data = json.load(f)
                        if "environment" in file_data:
                            environment = file_data["environment"].copy()
                        if "server_id" in file_data:
                            file_server_id = file_data["server_id"]
                except FileNotFoundError:
                    print(f"Error: Environment file not found: {args.env_file}", file=sys.stderr)
                    return EXIT_ERROR
                except json.JSONDecodeError as e:
                    print(f"Error: Invalid JSON in environment file: {e}", file=sys.stderr)
                    return EXIT_ERROR

            # Override with --env arguments (these take precedence)
            if hasattr(args, "env") and args.env:
                for env_var in args.env:
                    if "=" in env_var:
                        key, value = env_var.split("=", 1)
                        environment[key] = value
                    else:
                        print(
                            f"Warning: Skipping invalid environment variable: {env_var}",
                            file=sys.stderr,
                        )

            # Build create arguments
            create_args: Dict[str, Any] = {
                "name": args.name,
                "template": getattr(args, "template", "basic"),
                "environment": environment,
            }

            # Add optional arguments
            # Command-line --server takes precedence over file server_id
            if hasattr(args, "server") and args.server:
                create_args["server_id"] = args.server
            elif file_server_id:
                create_args["server_id"] = file_server_id

            if hasattr(args, "use_mock_llm") and args.use_mock_llm:
                create_args["use_mock_llm"] = args.use_mock_llm

            if hasattr(args, "enable_discord") and args.enable_discord:
                create_args["enable_discord"] = args.enable_discord

            if hasattr(args, "billing_enabled") and args.billing_enabled:
                create_args["billing_enabled"] = args.billing_enabled

            if hasattr(args, "billing_api_key") and args.billing_api_key:
                create_args["billing_api_key"] = args.billing_api_key

            if hasattr(args, "occurrence_id") and args.occurrence_id:
                create_args["agent_occurrence_id"] = args.occurrence_id

            if not ctx.quiet:
                print(f"Creating agent '{args.name}'...")

            result = ctx.client.create_agent(**create_args)

            if not ctx.quiet:
                print(f"Agent created successfully: {result.get('agent_id')}")

            # Format and print full result
            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error creating agent: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def delete(ctx: CommandContext, args: Namespace) -> int:
        """
        Delete an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, force)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            force = getattr(args, "force", False)

            # Get agent details for confirmation prompt
            if not force:
                try:
                    agent = ctx.client.get_agent(agent_id)
                    print(
                        f"About to delete agent: {agent.get('agent_id')} "
                        f"({agent.get('agent_name', 'Unknown')})"
                    )
                    print(f"Status: {agent.get('status', 'Unknown')}")

                    confirm = input("Are you sure? [y/N]: ")
                    if confirm.lower() != "y":
                        print("Cancelled.")
                        return EXIT_SUCCESS
                except APIError as e:
                    if e.status_code == 404:
                        print(f"Agent '{agent_id}' not found", file=sys.stderr)
                        return EXIT_NOT_FOUND
                    raise

            if not ctx.quiet:
                print(f"Deleting agent '{agent_id}'...")

            result = ctx.client.delete_agent(agent_id)

            if not ctx.quiet:
                print(f"Agent '{agent_id}' deleted successfully")

            # Print result details
            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error deleting agent: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def start(ctx: CommandContext, args: Namespace) -> int:
        """
        Start an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Starting agent '{agent_id}'...")

            result = ctx.client.start_agent(agent_id)

            if not ctx.quiet:
                print(f"Agent '{agent_id}' started successfully")

            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error starting agent: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def stop(ctx: CommandContext, args: Namespace) -> int:
        """
        Stop an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Stopping agent '{agent_id}'...")

            result = ctx.client.stop_agent(agent_id)

            if not ctx.quiet:
                print(f"Agent '{agent_id}' stopped successfully")

            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error stopping agent: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def restart(ctx: CommandContext, args: Namespace) -> int:
        """
        Restart an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Restarting agent '{agent_id}'...")

            result = ctx.client.restart_agent(agent_id)

            if not ctx.quiet:
                print(f"Agent '{agent_id}' restarted successfully")

            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error restarting agent: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def shutdown(ctx: CommandContext, args: Namespace) -> int:
        """
        Gracefully shutdown an agent.

        Note: This command sends a shutdown request to the agent, which is
        different from 'stop' which forcefully stops the container.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, message)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            message = getattr(args, "message", "")

            if not ctx.quiet:
                print(f"Sending shutdown request to agent '{agent_id}'...")

            # Get agent info to construct API endpoint
            agent = ctx.client.get_agent(agent_id)
            port = agent.get("api_port")

            if not port:
                print(
                    f"Error: Agent '{agent_id}' does not have an API port assigned",
                    file=sys.stderr,
                )
                return EXIT_ERROR

            # Make direct request to agent's shutdown endpoint
            # Note: The SDK doesn't have a shutdown method, so we construct the request manually
            base_url = ctx.client.base_url
            url = f"{base_url}/api/{agent_id}/v1/system/shutdown"

            import requests

            headers = {}
            if ctx.client.token:
                headers["Authorization"] = f"Bearer {ctx.client.token}"

            payload = {}
            if message:
                payload["message"] = message

            response = requests.post(url, json=payload, headers=headers)

            if response.status_code == 401:
                raise AuthenticationError("Authentication failed")
            elif response.status_code == 404:
                print(f"Agent '{agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            elif response.status_code >= 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("detail", f"API error: {response.status_code}")
                except Exception:
                    error_msg = f"API error: {response.status_code}"
                raise APIError(error_msg, response.status_code)

            result = response.json()

            if not ctx.quiet:
                print(f"Shutdown request sent to agent '{agent_id}'")

            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error sending shutdown request: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def logs(ctx: CommandContext, args: Namespace) -> int:
        """
        View agent logs.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, lines, follow)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            lines = getattr(args, "lines", 100)

            # Note: --follow is not implemented yet
            if hasattr(args, "follow") and args.follow:
                print(
                    "Warning: --follow option not yet implemented. Showing last logs only.",
                    file=sys.stderr,
                )

            if not ctx.quiet:
                print(f"Fetching logs for agent '{agent_id}'...")

            logs = ctx.client.get_agent_logs(agent_id, lines=lines)

            # Print logs directly (not formatted as JSON/YAML)
            print(logs)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error fetching logs: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def deploy(ctx: CommandContext, args: Namespace) -> int:
        """
        Deploy a specific version to an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, version, message, strategy)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            version = args.version
            message = getattr(args, "message", "CLI deployment")
            strategy = getattr(args, "strategy", "docker")

            # Construct the full image name
            if version == "latest":
                agent_image = "ghcr.io/cirisai/ciris-agent:latest"
            else:
                # Remove 'v' prefix if present
                clean_version = version[1:] if version.startswith("v") else version
                agent_image = f"ghcr.io/cirisai/ciris-agent:{clean_version}"

            if not ctx.quiet:
                print(f"Deploying {agent_image} to agent '{agent_id}'...")
                print(f"Strategy: {strategy}")
                print(f"Message: {message}")

            occurrence_id = getattr(args, "occurrence_id", None)
            server_id = getattr(args, "server_id", None)

            result = ctx.client.deploy_single_agent(
                agent_id=agent_id,
                agent_image=agent_image,
                message=message,
                strategy=strategy,
                metadata={"source": "cli"},
                occurrence_id=occurrence_id,
                server_id=server_id,
            )

            if not ctx.quiet:
                print("\nDeployment started successfully!")
                print(f"Deployment ID: {result.get('deployment_id')}")
                print(f"Status: {result.get('status')}")

            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error deploying to agent: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def versions(ctx: CommandContext, args: Namespace) -> int:
        """
        Show agent version information.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id - optional)

        Returns:
            Exit code
        """
        try:
            agent_id = getattr(args, "agent_id", None)

            if agent_id:
                # Show version for specific agent
                if not ctx.quiet:
                    print(f"Fetching version info for agent '{agent_id}'...")

                agent = ctx.client.get_agent(agent_id)

                # Extract version-related fields
                version_info = {
                    "agent_id": agent.get("agent_id"),
                    "agent_name": agent.get("agent_name"),
                    "version": agent.get("version"),
                    "codename": agent.get("codename"),
                    "code_hash": agent.get("code_hash"),
                    "image": agent.get("image"),
                    "status": agent.get("status"),
                    "update_available": agent.get("update_available", False),
                }

                output = formatter.format_output(version_info, ctx.output_format)
                print(output)
            else:
                # Show version for all agents
                if not ctx.quiet:
                    print("Fetching version info for all agents...")

                agents = ctx.client.list_agents()

                # Extract version-related fields from all agents
                version_list = []
                for agent in agents:
                    version_list.append(
                        {
                            "agent_id": agent.get("agent_id"),
                            "agent_name": agent.get("agent_name"),
                            "version": agent.get("version"),
                            "codename": agent.get("codename"),
                            "status": agent.get("status"),
                            "update_available": agent.get("update_available", False),
                        }
                    )

                if not version_list:
                    if not ctx.quiet:
                        print("No agents found")
                    return EXIT_SUCCESS

                # Define columns for table view
                columns = [
                    "agent_id",
                    "agent_name",
                    "version",
                    "codename",
                    "status",
                    "update_available",
                ]

                output = formatter.format_output(version_list, ctx.output_format, columns)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404 and agent_id:
                print(f"Agent '{agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error fetching version info: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR
