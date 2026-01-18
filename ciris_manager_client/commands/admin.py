"""
Admin action commands for CIRIS CLI.

This module provides commands for executing infrastructure-level
admin actions on agents (identity-update, restart, pull-image).

Note: Agent-side actions (pause/resume) must go through the H3ERE pipeline.
"""

import json
import sys
from argparse import Namespace

from ciris_manager_sdk import APIError, AuthenticationError
from ciris_manager_client.protocols import (
    CommandContext,
    EXIT_SUCCESS,
    EXIT_ERROR,
    EXIT_AUTH_ERROR,
    EXIT_API_ERROR,
    EXIT_NOT_FOUND,
)


class AdminCommands:
    """Admin action commands."""

    @staticmethod
    def list_actions(ctx: CommandContext, args: Namespace) -> int:
        """
        List available admin actions for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Listing admin actions for agent '{agent_id}'...")

            result = ctx.client.list_admin_actions(agent_id)

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            elif ctx.output_format == "yaml":
                try:
                    import yaml

                    print(yaml.dump(result, default_flow_style=False))
                except ImportError:
                    print(json.dumps(result, indent=2))
            else:
                # Table format
                actions = result.get("actions", [])
                if not actions:
                    print("No admin actions available.")
                    return EXIT_SUCCESS

                print(f"\nAvailable actions for {agent_id}:")
                print("-" * 60)
                for action in actions:
                    name = action.get("action", "unknown")
                    desc = action.get("description", "")
                    restart = action.get("requires_restart", False)
                    restart_indicator = " [restart]" if restart else ""
                    print(f"  {name}{restart_indicator}")
                    print(f"    {desc}")
                    params = action.get("params", {})
                    if params:
                        print(f"    Params: {params}")
                print()

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
            print(f"Error listing admin actions: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def execute(ctx: CommandContext, args: Namespace) -> int:
        """
        Execute an admin action on an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, action, params, force)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            action = args.action

            if not ctx.quiet:
                print(f"Executing action '{action}' on agent '{agent_id}'...")

            # Parse params from command line
            params = None
            if hasattr(args, "params") and args.params:
                try:
                    params = json.loads(args.params)
                except json.JSONDecodeError:
                    print(f"Error: params must be valid JSON", file=sys.stderr)
                    return EXIT_ERROR

            force = getattr(args, "force", False)

            result = ctx.client.execute_admin_action(
                agent_id=agent_id,
                action=action,
                params=params,
                force=force,
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                success = result.get("success", False)
                message = result.get("message", "Action completed")
                details = result.get("details", {})

                if success:
                    print(f"\n{message}")
                    if details:
                        print("\nDetails:")
                        for key, value in details.items():
                            print(f"  {key}: {value}")
                else:
                    print(f"\nAction failed: {message}", file=sys.stderr)
                    return EXIT_ERROR

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
            print(f"Error executing admin action: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def identity_update(ctx: CommandContext, args: Namespace) -> int:
        """
        Trigger identity update for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, template, force)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            template = getattr(args, "template", None)
            force = getattr(args, "force", False)

            if not ctx.quiet:
                msg = f"Triggering identity update for agent '{agent_id}'..."
                if template:
                    msg += f" (template: {template})"
                print(msg)

            result = ctx.client.trigger_identity_update(
                agent_id=agent_id,
                template=template,
                force=force,
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                success = result.get("success", False)
                message = result.get("message", "Identity update triggered")
                details = result.get("details", {})

                if success:
                    print(f"\n{message}")
                    if details:
                        print("\nDetails:")
                        for key, value in details.items():
                            print(f"  {key}: {value}")
                else:
                    print(f"\nAction failed: {message}", file=sys.stderr)
                    return EXIT_ERROR

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
            print(f"Error triggering identity update: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def pull_image(ctx: CommandContext, args: Namespace) -> int:
        """
        Pull latest Docker image for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Pulling latest image for agent '{agent_id}'...")

            result = ctx.client.pull_agent_image(agent_id)

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                success = result.get("success", False)
                message = result.get("message", "Image pulled")
                details = result.get("details", {})

                if success:
                    print(f"\n{message}")
                    if details.get("image"):
                        print(f"  Image: {details['image']}")
                else:
                    print(f"\nAction failed: {message}", file=sys.stderr)
                    return EXIT_ERROR

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
            print(f"Error pulling image: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR
