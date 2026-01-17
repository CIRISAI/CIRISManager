"""
LLM configuration commands for CIRIS CLI.

This module provides commands for managing LLM provider configurations
on CIRIS agents including getting, setting, and validating configs.
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


# Provider choices for argument validation
PROVIDERS = ["openai", "together", "groq", "openrouter", "custom"]


class LLMCommands:
    """LLM configuration management commands."""

    @staticmethod
    def get(ctx: CommandContext, args: Namespace) -> int:
        """
        Get LLM configuration for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments (agent_id)

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Fetching LLM configuration for agent '{agent_id}'...")

            result = ctx.client.get_llm_config(
                agent_id,
                occurrence_id=getattr(args, "occurrence_id", None),
                server_id=getattr(args, "server_id", None),
            )

            llm_config = result.get("llm_config")

            if not llm_config:
                if not ctx.quiet:
                    print(f"No LLM configuration set for agent '{agent_id}'")
                    print("Agent is using environment variables or defaults.")
                if ctx.output_format == "json":
                    print(json.dumps(result, indent=2))
                return EXIT_SUCCESS

            # Format output based on format setting
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
                _print_llm_config_table(llm_config)

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
            print(f"Error getting LLM config: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def set(ctx: CommandContext, args: Namespace) -> int:
        """
        Set LLM configuration for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                action = "Setting" if not getattr(args, "no_restart", False) else "Updating"
                print(f"{action} LLM configuration for agent '{agent_id}'...")

            # Call SDK method
            result = ctx.client.set_llm_config(
                agent_id=agent_id,
                primary_provider=args.provider,
                primary_api_key=args.api_key,
                primary_model=args.model,
                primary_api_base=getattr(args, "api_base", None),
                backup_provider=getattr(args, "backup_provider", None),
                backup_api_key=getattr(args, "backup_api_key", None),
                backup_model=getattr(args, "backup_model", None),
                backup_api_base=getattr(args, "backup_api_base", None),
                validate=not getattr(args, "no_validate", False),
                restart=not getattr(args, "no_restart", False),
                occurrence_id=getattr(args, "occurrence_id", None),
                server_id=getattr(args, "server_id", None),
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                message = result.get("message", "LLM configuration updated")
                print(f"\n{message}")

                # Show validation results if available
                validation = result.get("validation")
                if validation and validation != "skipped":
                    print("\nValidation Results:")
                    if "primary" in validation:
                        primary_valid = validation["primary"].get("valid", False)
                        status = "Valid" if primary_valid else "Invalid"
                        print(f"  Primary: {status}")
                        if not primary_valid and validation["primary"].get("error"):
                            print(f"    Error: {validation['primary']['error']}")
                    if "backup" in validation:
                        backup_valid = validation["backup"].get("valid", False)
                        status = "Valid" if backup_valid else "Invalid"
                        print(f"  Backup: {status}")
                        if not backup_valid and validation["backup"].get("error"):
                            print(f"    Error: {validation['backup']['error']}")

                if result.get("warning"):
                    print(f"\nWarning: {result['warning']}")

            return EXIT_SUCCESS

        except AuthenticationError as e:
            print(f"Authentication error: {e}", file=sys.stderr)
            return EXIT_AUTH_ERROR
        except APIError as e:
            if e.status_code == 400:
                # Validation failure
                error_detail = e.response.get("detail", str(e)) if e.response else str(e)
                print(f"Validation failed: {error_detail}", file=sys.stderr)
                return EXIT_ERROR
            if e.status_code == 404:
                print(f"Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"API error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
        except Exception as e:
            print(f"Error setting LLM config: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def delete(ctx: CommandContext, args: Namespace) -> int:
        """
        Delete LLM configuration for an agent.

        Args:
            ctx: Command context
            args: Parsed arguments

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Deleting LLM configuration for agent '{agent_id}'...")

            result = ctx.client.delete_llm_config(
                agent_id=agent_id,
                restart=not getattr(args, "no_restart", False),
                occurrence_id=getattr(args, "occurrence_id", None),
                server_id=getattr(args, "server_id", None),
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                message = result.get("message", "LLM configuration deleted")
                print(f"\n{message}")

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
            print(f"Error deleting LLM config: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR

    @staticmethod
    def validate(ctx: CommandContext, args: Namespace) -> int:
        """
        Validate LLM configuration without saving.

        Args:
            ctx: Command context
            args: Parsed arguments

        Returns:
            Exit code
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Validating LLM configuration for provider '{args.provider}'...")

            result = ctx.client.validate_llm_config(
                agent_id=agent_id,
                provider=args.provider,
                api_key=args.api_key,
                model=args.model,
                api_base=getattr(args, "api_base", None),
                occurrence_id=getattr(args, "occurrence_id", None),
                server_id=getattr(args, "server_id", None),
            )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                is_valid = result.get("valid", False)
                if is_valid:
                    print(f"\nAPI key is valid for {args.provider}")
                    models = result.get("models_available", [])
                    if models:
                        print(f"\nAvailable models ({len(models)} shown):")
                        for model in models[:10]:  # Show first 10
                            marker = "*" if model == args.model else " "
                            print(f"  {marker} {model}")
                        if len(models) > 10:
                            print(f"  ... and {len(models) - 10} more")
                else:
                    error = result.get("error", "Unknown error")
                    print(f"\nValidation failed: {error}")

            return EXIT_SUCCESS if result.get("valid", False) else EXIT_ERROR

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
            print(f"Error validating LLM config: {e}", file=sys.stderr)
            if ctx.verbose:
                import traceback

                traceback.print_exc()
            return EXIT_ERROR


def _print_llm_config_table(llm_config: Dict[str, Any]) -> None:
    """
    Print LLM configuration in a readable table format.

    Args:
        llm_config: LLM configuration dict
    """
    primary = llm_config.get("primary", {})
    backup = llm_config.get("backup")

    print("\n=== Primary LLM Configuration ===")
    print(f"  Provider:  {primary.get('provider', 'N/A')}")
    print(f"  Model:     {primary.get('model', 'N/A')}")
    print(f"  API Key:   {primary.get('api_key_hint', 'N/A')}")
    print(f"  API Base:  {primary.get('api_base', 'N/A')}")

    if backup:
        print("\n=== Backup LLM Configuration ===")
        print(f"  Provider:  {backup.get('provider', 'N/A')}")
        print(f"  Model:     {backup.get('model', 'N/A')}")
        print(f"  API Key:   {backup.get('api_key_hint', 'N/A')}")
        print(f"  API Base:  {backup.get('api_base', 'N/A')}")
    else:
        print("\n=== Backup LLM Configuration ===")
        print("  Not configured")

    print()
