"""
Adapter management commands for CIRIS CLI.

This module provides commands for managing adapters on CIRIS agents including
listing, loading, unloading, and configuration via wizard.
"""

import json
import sys
from argparse import Namespace
from typing import Any, Dict

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


class AdapterCommands:
    """Adapter management commands."""

    @staticmethod
    def list(ctx: CommandContext, args: Namespace) -> int:
        """
        List all available adapters with their status.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Fetching adapters for agent '{agent_id}'...")

            result = ctx.client.list_adapter_manifests(agent_id)
            adapters = result.get("adapters", [])

            if not adapters:
                if not ctx.quiet:
                    print("No adapters available")
                return EXIT_SUCCESS

            # Define columns for table view
            columns = [
                "adapter_type",
                "name",
                "status",
                "version",
                "has_wizard",
                "requires_consent",
            ]

            output = formatter.format_output(adapters, ctx.output_format, columns)
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
            print(f"Error listing adapters: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def types(ctx: CommandContext, args: Namespace) -> int:
        """
        List available adapter types on an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Fetching adapter types for agent '{agent_id}'...")

            result = ctx.client.list_adapter_types(agent_id)

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
            print(f"Error listing adapter types: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def get(ctx: CommandContext, args: Namespace) -> int:
        """
        Get status of a specific adapter.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_id = args.adapter_id

            if not ctx.quiet:
                print(f"Fetching adapter '{adapter_id}' on agent '{agent_id}'...")

            result = ctx.client.get_adapter(agent_id, adapter_id)

            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Adapter '{args.adapter_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error getting adapter: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def manifest(ctx: CommandContext, args: Namespace) -> int:
        """
        Get full manifest for a specific adapter type.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_type)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_type = args.adapter_type

            if not ctx.quiet:
                print(f"Fetching manifest for '{adapter_type}' on agent '{agent_id}'...")

            result = ctx.client.get_adapter_manifest(agent_id, adapter_type)

            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Adapter type '{args.adapter_type}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error getting manifest: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def load(ctx: CommandContext, args: Namespace) -> int:
        """
        Load/create a new adapter on an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_type, config_file, no_auto_start)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_type = args.adapter_type
            auto_start = not getattr(args, "no_auto_start", False)
            adapter_id = getattr(args, "adapter_id", None)

            # Load config from file if provided
            config: Dict[str, Any] = {}
            config_file = getattr(args, "config_file", None)
            if config_file:
                try:
                    with open(config_file, "r") as f:
                        config = json.load(f)
                except FileNotFoundError:
                    print(f"Error: Config file not found: {config_file}", file=sys.stderr)
                    return EXIT_ERROR
                except json.JSONDecodeError as e:
                    print(f"Error: Invalid JSON in config file: {e}", file=sys.stderr)
                    return EXIT_ERROR

            if not ctx.quiet:
                print(f"Loading adapter '{adapter_type}' on agent '{agent_id}'...")

            result = ctx.client.load_adapter(
                agent_id,
                adapter_type,
                config=config if config else None,
                auto_start=auto_start,
                adapter_id=adapter_id,
            )

            if not ctx.quiet:
                print(f"Adapter '{adapter_type}' loaded successfully")

            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print("Agent or adapter type not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error loading adapter: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def unload(ctx: CommandContext, args: Namespace) -> int:
        """
        Unload/stop an adapter on an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_id = args.adapter_id

            if not ctx.quiet:
                print(f"Unloading adapter '{adapter_id}' from agent '{agent_id}'...")

            result = ctx.client.unload_adapter(agent_id, adapter_id)

            if not ctx.quiet:
                print(f"Adapter '{adapter_id}' unloaded successfully")

            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Adapter '{args.adapter_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error unloading adapter: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def reload(ctx: CommandContext, args: Namespace) -> int:
        """
        Reload an adapter with new configuration.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_id, config_file, no_auto_start)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_id = args.adapter_id
            auto_start = not getattr(args, "no_auto_start", False)

            # Load config from file if provided
            config: Dict[str, Any] = {}
            config_file = getattr(args, "config_file", None)
            if config_file:
                try:
                    with open(config_file, "r") as f:
                        config = json.load(f)
                except FileNotFoundError:
                    print(f"Error: Config file not found: {config_file}", file=sys.stderr)
                    return EXIT_ERROR
                except json.JSONDecodeError as e:
                    print(f"Error: Invalid JSON in config file: {e}", file=sys.stderr)
                    return EXIT_ERROR

            if not ctx.quiet:
                print(f"Reloading adapter '{adapter_id}' on agent '{agent_id}'...")

            result = ctx.client.reload_adapter(
                agent_id,
                adapter_id,
                config=config if config else None,
                auto_start=auto_start,
            )

            if not ctx.quiet:
                print(f"Adapter '{adapter_id}' reloaded successfully")

            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Adapter '{args.adapter_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error reloading adapter: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def configs(ctx: CommandContext, args: Namespace) -> int:
        """
        Get all persisted adapter configurations for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Fetching adapter configurations for agent '{agent_id}'...")

            result = ctx.client.get_adapter_configs(agent_id)
            configs = result.get("configs", {})

            if not configs:
                if not ctx.quiet:
                    print("No adapter configurations found")
                return EXIT_SUCCESS

            output = formatter.format_output(configs, ctx.output_format)
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
            print(f"Error getting configurations: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def remove_config(ctx: CommandContext, args: Namespace) -> int:
        """
        Remove adapter configuration from registry.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_type, force)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_type = args.adapter_type
            force = getattr(args, "force", False)

            if not force:
                confirm = input(
                    f"Remove configuration for '{adapter_type}' on agent '{agent_id}'? [y/N]: "
                )
                if confirm.lower() != "y":
                    print("Cancelled.")
                    return EXIT_SUCCESS

            if not ctx.quiet:
                print(f"Removing configuration for '{adapter_type}'...")

            result = ctx.client.remove_adapter_config(agent_id, adapter_type)

            if not ctx.quiet:
                print(f"Configuration for '{adapter_type}' removed")
                if result.get("adapter_unloaded"):
                    print("Adapter was also unloaded from the agent")
                else:
                    print("Note: Adapter may still be running until agent restart")

            if ctx.verbose:
                output = formatter.format_output(result, ctx.output_format)
                print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(
                    f"Configuration for '{args.adapter_type}' not found",
                    file=sys.stderr,
                )
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error removing configuration: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def wizard_start(ctx: CommandContext, args: Namespace) -> int:
        """
        Start a wizard session for configuring an adapter.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_type, resume)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_type = args.adapter_type
            resume_from = getattr(args, "resume", None)

            if not ctx.quiet:
                action = "Resuming" if resume_from else "Starting"
                print(f"{action} wizard for '{adapter_type}' on agent '{agent_id}'...")

            result = ctx.client.start_adapter_wizard(
                agent_id, adapter_type, resume_from=resume_from
            )

            if not ctx.quiet:
                print(f"\nWizard Session: {result.get('session_id')}")
                print(f"Current Step: {result.get('current_step')}")
                print(f"Steps Remaining: {', '.join(result.get('steps_remaining', []))}")
                print(f"Expires At: {result.get('expires_at')}")
                print("\nUse 'adapter wizard-step' to proceed through the wizard.")

            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 404:
                print(f"Adapter type '{args.adapter_type}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            if e.status_code == 400:
                print(f"Wizard error: {e}", file=sys.stderr)
                return EXIT_ERROR
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error starting wizard: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def wizard_step(ctx: CommandContext, args: Namespace) -> int:
        """
        Execute a wizard step.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_type, session_id, step_id, data, skip)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_type = args.adapter_type
            session_id = args.session_id
            step_id = args.step_id
            action = "skip" if getattr(args, "skip", False) else "execute"

            # Parse data from --data arguments
            data: Dict[str, Any] = {}
            data_args = getattr(args, "data", None)
            if data_args:
                for item in data_args:
                    if "=" in item:
                        key, value = item.split("=", 1)
                        # Try to parse as JSON for complex values
                        try:
                            data[key] = json.loads(value)
                        except json.JSONDecodeError:
                            data[key] = value
                    else:
                        print(f"Warning: Skipping invalid data item: {item}", file=sys.stderr)

            # Also accept JSON file
            data_file = getattr(args, "data_file", None)
            if data_file:
                try:
                    with open(data_file, "r") as f:
                        file_data = json.load(f)
                        data.update(file_data)
                except FileNotFoundError:
                    print(f"Error: Data file not found: {data_file}", file=sys.stderr)
                    return EXIT_ERROR
                except json.JSONDecodeError as e:
                    print(f"Error: Invalid JSON in data file: {e}", file=sys.stderr)
                    return EXIT_ERROR

            if not ctx.quiet:
                action_str = "Skipping" if action == "skip" else "Executing"
                print(f"{action_str} step '{step_id}'...")

            result = ctx.client.execute_wizard_step(
                agent_id, adapter_type, session_id, step_id, data=data, action=action
            )

            if not ctx.quiet:
                status = result.get("status", "unknown")
                print(f"Status: {status}")

                if result.get("validation"):
                    validation = result["validation"]
                    if not validation.get("valid"):
                        print("Validation errors:")
                        for error in validation.get("errors", []):
                            print(f"  - {error}")

                if result.get("next_step"):
                    print(f"Next Step: {result['next_step']}")
                else:
                    print("No more steps. Use 'adapter wizard-complete' to finish.")

            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 410:
                print("Wizard session expired or not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            if e.status_code == 400:
                print(f"Step error: {e}", file=sys.stderr)
                return EXIT_ERROR
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error executing step: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def wizard_complete(ctx: CommandContext, args: Namespace) -> int:
        """
        Complete the wizard and apply configuration.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id, adapter_type, session_id, no_confirm)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id
            adapter_type = args.adapter_type
            session_id = args.session_id
            confirm = not getattr(args, "no_confirm", False)

            if not ctx.quiet:
                print(f"Completing wizard for '{adapter_type}'...")

            result = ctx.client.complete_adapter_wizard(
                agent_id, adapter_type, session_id, confirm=confirm
            )

            if not ctx.quiet:
                print("\nWizard completed successfully!")
                print(f"Adapter: {result.get('adapter_type')}")
                print(f"Config Applied: {result.get('config_applied')}")
                print(f"Compose Regenerated: {result.get('compose_regenerated')}")
                print(f"Adapter Loaded: {result.get('adapter_loaded')}")

                if result.get("restart_required"):
                    print("\nNote: Agent restart required to apply changes")
                print(f"\nMessage: {result.get('message')}")

            output = formatter.format_output(result, ctx.output_format)
            print(output)

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 410:
                print("Wizard session expired or not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            if e.status_code == 400:
                print(f"Completion error: {e}", file=sys.stderr)
                return EXIT_ERROR
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error completing wizard: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR
