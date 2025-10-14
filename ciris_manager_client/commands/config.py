"""
Configuration management commands for CIRIS CLI.

Provides commands to get, update, export, import, backup, and restore
agent configurations.
"""

import sys
import json
from pathlib import Path
from typing import Any, Dict, Optional, cast
from argparse import Namespace
from datetime import datetime

from ciris_manager_client.protocols import (
    CommandContext,
    EXIT_SUCCESS,
    EXIT_ERROR,
    EXIT_API_ERROR,
    EXIT_VALIDATION_ERROR,
    EXIT_NOT_FOUND,
)
from ciris_manager.models.agent import AgentConfig
from ciris_manager.models.backup import AgentBackup, AgentBackupData, BackupMetadata


def load_config_file(file_path: str) -> Dict[str, Any]:
    """
    Load configuration from a file (JSON or YAML).

    Args:
        file_path: Path to configuration file

    Returns:
        Dictionary containing configuration data

    Raises:
        ValueError: If file format is unsupported
        FileNotFoundError: If file doesn't exist
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    content = path.read_text()
    file_ext = path.suffix.lower()

    if file_ext == ".json":
        return cast(Dict[str, Any], json.loads(content))
    elif file_ext in (".yaml", ".yml"):
        try:
            import yaml

            return cast(Dict[str, Any], yaml.safe_load(content))
        except ImportError:
            raise ValueError(
                "PyYAML is required to load YAML files. Install with: pip install pyyaml"
            )
    else:
        # Try to detect format from content
        content = content.strip()
        if content.startswith("{"):
            return cast(Dict[str, Any], json.loads(content))
        else:
            try:
                import yaml

                return cast(Dict[str, Any], yaml.safe_load(content))
            except ImportError:
                raise ValueError(f"Unsupported file format: {file_ext}. Use .json or .yaml")


def save_config_file(file_path: str, data: Any, format: Optional[str] = None) -> None:
    """
    Save configuration to a file (JSON or YAML).

    Args:
        file_path: Path to save configuration
        data: Data to save
        format: Format to use ('json' or 'yaml'). If None, infer from file extension

    Raises:
        ValueError: If format is unsupported
    """
    path = Path(file_path)

    # Determine format
    if format:
        file_format = format.lower()
    else:
        file_ext = path.suffix.lower()
        if file_ext == ".json":
            file_format = "json"
        elif file_ext in (".yaml", ".yml"):
            file_format = "yaml"
        else:
            # Default to JSON
            file_format = "json"

    # Create parent directory if needed
    path.parent.mkdir(parents=True, exist_ok=True)

    # Convert Pydantic models to dict if needed
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    elif hasattr(data, "dict"):
        data = data.dict()

    # Write file
    if file_format == "json":
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    elif file_format == "yaml":
        try:
            import yaml

            with open(path, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        except ImportError:
            raise ValueError(
                "PyYAML is required to save YAML files. Install with: pip install pyyaml"
            )
    else:
        raise ValueError(f"Unsupported format: {file_format}. Use 'json' or 'yaml'")


class ConfigCommands:
    """Configuration management commands."""

    @staticmethod
    def get(ctx: CommandContext, args: Namespace) -> int:
        """
        Get agent configuration.

        Args:
            ctx: Command context with client and settings
            args: Parsed arguments with agent_id

        Returns:
            Exit code (0 for success)
        """
        try:
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Fetching configuration for agent: {agent_id}", file=sys.stderr)

            # Get config from API
            config = ctx.client.get_agent_config(agent_id)

            # Output based on format
            if ctx.output_format == "json":
                print(json.dumps(config, indent=2))
            elif ctx.output_format == "yaml":
                try:
                    import yaml

                    print(yaml.safe_dump(config, default_flow_style=False, sort_keys=False))
                except ImportError:
                    print(
                        "Error: PyYAML is required for YAML output. Install with: pip install pyyaml",
                        file=sys.stderr,
                    )
                    return EXIT_ERROR
            else:
                # Table format - show key info
                print(f"Agent ID: {config.get('agent_id')}")
                print(f"Name: {config.get('name', 'N/A')}")
                print(f"Port: {config.get('port', 'N/A')}")
                print(f"Template: {config.get('template', 'N/A')}")
                print(f"Compose File: {config.get('compose_file', 'N/A')}")
                print("\nEnvironment Variables:")
                env = config.get("environment", {})
                if env:
                    for key, value in sorted(env.items()):
                        # Mask sensitive values
                        if any(s in key.upper() for s in ["KEY", "SECRET", "PASSWORD", "TOKEN"]):
                            value = "***REDACTED***"
                        print(f"  {key}={value}")
                else:
                    print("  (none)")

            return EXIT_SUCCESS

        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower():
                print(f"Error: Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"Error: {error_msg}", file=sys.stderr)
            return EXIT_API_ERROR

    @staticmethod
    def update(ctx: CommandContext, args: Namespace) -> int:
        """
        Update agent configuration.

        Args:
            ctx: Command context with client and settings
            args: Parsed arguments with agent_id, env list, from_file

        Returns:
            Exit code (0 for success)
        """
        try:
            agent_id = args.agent_id
            environment = {}

            # Load from file if specified
            if hasattr(args, "from_file") and args.from_file:
                if not ctx.quiet:
                    print(f"Loading configuration from: {args.from_file}", file=sys.stderr)

                try:
                    file_data = load_config_file(args.from_file)
                    environment = file_data.get("environment", file_data)
                except Exception as e:
                    print(f"Error loading configuration file: {e}", file=sys.stderr)
                    return EXIT_ERROR

            # Parse --env arguments
            if hasattr(args, "env") and args.env:
                for env_str in args.env:
                    if "=" not in env_str:
                        print(
                            f"Error: Invalid environment variable format: {env_str}",
                            file=sys.stderr,
                        )
                        print("Use format: KEY=VALUE", file=sys.stderr)
                        return EXIT_ERROR
                    key, value = env_str.split("=", 1)
                    environment[key] = value

            if not environment:
                print(
                    "Error: No environment variables specified. Use --env KEY=VALUE or --from-file",
                    file=sys.stderr,
                )
                return EXIT_ERROR

            if not ctx.quiet:
                print(f"Updating configuration for agent: {agent_id}", file=sys.stderr)
                if ctx.verbose:
                    print("Environment updates:", file=sys.stderr)
                    for key, value in environment.items():
                        print(f"  {key}={value}", file=sys.stderr)

            # Update via API
            update_data = {"environment": environment, "restart": True}
            result = ctx.client.update_agent_config(agent_id, update_data)

            if not ctx.quiet:
                print(f"Configuration updated successfully for agent: {agent_id}", file=sys.stderr)

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                print(f"Status: {result.get('status', 'updated')}")

            return EXIT_SUCCESS

        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower():
                print(f"Error: Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"Error: {error_msg}", file=sys.stderr)
            return EXIT_API_ERROR

    @staticmethod
    def export(ctx: CommandContext, args: Namespace) -> int:
        """
        Export agent configuration to file.

        Args:
            ctx: Command context with client and settings
            args: Parsed arguments with agent_id, output, format, server

        Returns:
            Exit code (0 for success)
        """
        try:
            # Handle server-wide export
            if hasattr(args, "server") and args.server:
                if not ctx.quiet:
                    print(f"Exporting all agents from server: {args.server}", file=sys.stderr)

                # Get all agents
                agents = ctx.client.list_agents()
                server_agents = [a for a in agents if a.get("server_id") == args.server]

                if not server_agents:
                    print(f"No agents found on server: {args.server}", file=sys.stderr)
                    return EXIT_NOT_FOUND

                # Export each agent
                all_configs = {}
                for agent in server_agents:
                    agent_id = agent["agent_id"]
                    try:
                        config = ctx.client.get_agent_config(agent_id)
                        all_configs[agent_id] = config
                    except Exception as e:
                        if not ctx.quiet:
                            print(f"Warning: Failed to export {agent_id}: {e}", file=sys.stderr)

                data_to_export = {
                    "server_id": args.server,
                    "exported_at": datetime.utcnow().isoformat(),
                    "agent_count": len(all_configs),
                    "agents": all_configs,
                }

                # Save to file
                output_file = (
                    args.output
                    or f"agents_{args.server}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
                )
                save_config_file(output_file, data_to_export, format=getattr(args, "format", None))

                if not ctx.quiet:
                    print(f"Exported {len(all_configs)} agents to: {output_file}", file=sys.stderr)

                return EXIT_SUCCESS

            # Single agent export
            agent_id = args.agent_id

            if not ctx.quiet:
                print(f"Exporting configuration for agent: {agent_id}", file=sys.stderr)

            # Get config from API
            config = ctx.client.get_agent_config(agent_id)

            # Determine output file
            if hasattr(args, "output") and args.output:
                output_file = args.output
            else:
                # Default filename based on agent_id
                ext = "json" if ctx.output_format == "json" else "yaml"
                if hasattr(args, "format") and args.format:
                    ext = args.format
                output_file = f"{agent_id}_config.{ext}"

            # Save to file
            save_config_file(output_file, config, format=getattr(args, "format", None))

            if not ctx.quiet:
                print(f"Configuration exported to: {output_file}", file=sys.stderr)

            return EXIT_SUCCESS

        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg or "not found" in error_msg.lower():
                print(f"Error: Agent '{args.agent_id}' not found", file=sys.stderr)
                return EXIT_NOT_FOUND
            print(f"Error: {error_msg}", file=sys.stderr)
            return EXIT_API_ERROR

    @staticmethod
    def import_config(ctx: CommandContext, args: Namespace) -> int:
        """
        Import agent configuration from file.

        Args:
            ctx: Command context with client and settings
            args: Parsed arguments with file, dry_run, agent_id override

        Returns:
            Exit code (0 for success)
        """
        try:
            file_path = args.file

            if not ctx.quiet:
                print(f"Loading configuration from: {file_path}", file=sys.stderr)

            # Load configuration file
            try:
                config_data = load_config_file(file_path)
            except FileNotFoundError:
                print(f"Error: File not found: {file_path}", file=sys.stderr)
                return EXIT_ERROR
            except Exception as e:
                print(f"Error loading file: {e}", file=sys.stderr)
                return EXIT_ERROR

            # Validate using Pydantic model
            try:
                config = AgentConfig(**config_data)
            except Exception as e:
                print(f"Error: Invalid configuration format: {e}", file=sys.stderr)
                return EXIT_VALIDATION_ERROR

            # Override agent_id if specified
            if hasattr(args, "agent_id") and args.agent_id:
                original_id = config.agent_id
                config.agent_id = args.agent_id
                if not ctx.quiet:
                    print(f"Overriding agent_id: {original_id} -> {args.agent_id}", file=sys.stderr)

            # Dry-run mode
            if hasattr(args, "dry_run") and args.dry_run:
                print("DRY RUN - No changes will be made", file=sys.stderr)
                print(f"\nWould import configuration for agent: {config.agent_id}")
                print(f"  Name: {config.name}")
                print(f"  Template: {config.template}")
                print(f"  Port: {config.port}")
                print(f"  Environment variables: {len(config.environment)}")
                if ctx.verbose:
                    print("\nEnvironment variables:")
                    for key, value in config.environment.items():
                        # Mask sensitive values
                        if any(s in key.upper() for s in ["KEY", "SECRET", "PASSWORD", "TOKEN"]):
                            value = "***REDACTED***"
                        print(f"  {key}={value}")
                return EXIT_SUCCESS

            # Import configuration
            if not ctx.quiet:
                print(f"Importing configuration for agent: {config.agent_id}", file=sys.stderr)

            # Check if agent exists
            try:
                ctx.client.get_agent(config.agent_id)
                if not ctx.quiet:
                    print(
                        f"Agent {config.agent_id} exists, updating configuration...",
                        file=sys.stderr,
                    )

                # Update existing agent
                update_data = {"environment": config.environment, "restart": True}
                result = ctx.client.update_agent_config(config.agent_id, update_data)

            except Exception as e:
                # Agent doesn't exist, create it
                if "404" in str(e) or "not found" in str(e).lower():
                    if not ctx.quiet:
                        print(
                            f"Agent {config.agent_id} not found, creating new agent...",
                            file=sys.stderr,
                        )

                    result = ctx.client.create_agent(
                        name=config.name,
                        template=config.template,
                        environment=config.environment,
                    )
                else:
                    raise

            if not ctx.quiet:
                print(
                    f"Configuration imported successfully for agent: {config.agent_id}",
                    file=sys.stderr,
                )

            if ctx.output_format == "json":
                print(json.dumps(result, indent=2))
            else:
                print(f"Status: {result.get('status', 'imported')}")

            return EXIT_SUCCESS

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return EXIT_API_ERROR

    @staticmethod
    def backup(ctx: CommandContext, args: Namespace) -> int:
        """
        Backup all agent configurations.

        Args:
            ctx: Command context with client and settings
            args: Parsed arguments with output, server

        Returns:
            Exit code (0 for success)
        """
        try:
            if not ctx.quiet:
                print("Creating backup of agent configurations...", file=sys.stderr)

            # Get all agents
            agents = ctx.client.list_agents()

            # Filter by server if specified
            if hasattr(args, "server") and args.server:
                agents = [a for a in agents if a.get("server_id") == args.server]
                if not ctx.quiet:
                    print(f"Filtering to server: {args.server}", file=sys.stderr)

            if not agents:
                print("No agents found to backup", file=sys.stderr)
                return EXIT_ERROR

            # Fetch configurations for all agents
            agent_configs = []
            failed_agents = []

            for agent in agents:
                agent_id = agent["agent_id"]
                try:
                    if ctx.verbose:
                        print(f"Backing up agent: {agent_id}", file=sys.stderr)

                    config = ctx.client.get_agent_config(agent_id)

                    # Convert to AgentBackupData
                    backup_data = AgentBackupData(
                        agent_id=config.get("agent_id"),
                        name=config.get("name", agent_id),
                        port=config.get("port", 0),
                        template=config.get("template", "unknown"),
                        compose_file=config.get("compose_file", ""),
                        created_at=config.get("created_at", datetime.utcnow().isoformat()),
                        metadata=config.get("metadata", {}),
                        oauth_status=config.get("oauth_status"),
                        service_token=config.get("service_token"),
                        admin_password=config.get("admin_password"),
                        current_version=config.get("current_version"),
                        last_work_state_at=config.get("last_work_state_at"),
                        version_transitions=config.get("version_transitions", []),
                        do_not_autostart=config.get("do_not_autostart", False),
                        server_id=config.get("server_id", "main"),
                        environment_vars=config.get("environment", {}),
                    )
                    agent_configs.append(backup_data)

                except Exception as e:
                    failed_agents.append(agent_id)
                    if not ctx.quiet:
                        print(f"Warning: Failed to backup {agent_id}: {e}", file=sys.stderr)

            if not agent_configs:
                print("Error: No agent configurations could be backed up", file=sys.stderr)
                return EXIT_ERROR

            # Create backup metadata
            timestamp = datetime.utcnow()
            metadata = BackupMetadata(
                timestamp=timestamp.strftime("%Y%m%d_%H%M%S"),
                date=timestamp.isoformat(),
                hostname="cli-backup",
                version="1.0",
                included_paths=[],
                backup_size="N/A",
                agent_count=len(agent_configs),
                agents=[a.agent_id for a in agent_configs],
                description=f"CLI backup of {len(agent_configs)} agents",
            )

            # Create backup bundle
            backup = AgentBackup(
                metadata=metadata,
                agents=agent_configs,
                registry_version="1.0",
                port_allocations={a.agent_id: a.port for a in agent_configs},
            )

            # Determine output file
            if hasattr(args, "output") and args.output:
                output_file = args.output
            else:
                server_suffix = f"_{args.server}" if hasattr(args, "server") and args.server else ""
                output_file = f"ciris_backup{server_suffix}_{metadata.timestamp}.json"

            # Save backup
            save_config_file(output_file, backup, format="json")

            if not ctx.quiet:
                print("\nBackup completed successfully!", file=sys.stderr)
                print(f"  Agents backed up: {len(agent_configs)}", file=sys.stderr)
                if failed_agents:
                    print(f"  Failed agents: {len(failed_agents)}", file=sys.stderr)
                print(f"  Backup file: {output_file}", file=sys.stderr)

            # Output summary
            if ctx.output_format == "json":
                summary = {
                    "success": True,
                    "backup_file": output_file,
                    "agent_count": len(agent_configs),
                    "agents": [a.agent_id for a in agent_configs],
                    "failed": failed_agents,
                }
                print(json.dumps(summary, indent=2))
            else:
                print(f"\nBackup saved to: {output_file}")

            return EXIT_SUCCESS

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return EXIT_API_ERROR

    @staticmethod
    def restore(ctx: CommandContext, args: Namespace) -> int:
        """
        Restore agent configurations from backup.

        Args:
            ctx: Command context with client and settings
            args: Parsed arguments with file, agent_id, dry_run

        Returns:
            Exit code (0 for success)
        """
        try:
            file_path = args.file

            if not ctx.quiet:
                print(f"Loading backup from: {file_path}", file=sys.stderr)

            # Load backup file
            try:
                backup_data = load_config_file(file_path)
            except FileNotFoundError:
                print(f"Error: Backup file not found: {file_path}", file=sys.stderr)
                return EXIT_ERROR
            except Exception as e:
                print(f"Error loading backup file: {e}", file=sys.stderr)
                return EXIT_ERROR

            # Validate backup format
            try:
                backup = AgentBackup(**backup_data)
            except Exception as e:
                print(f"Error: Invalid backup format: {e}", file=sys.stderr)
                return EXIT_VALIDATION_ERROR

            # Filter agents if specific agent_id requested
            agents_to_restore = backup.agents
            if hasattr(args, "agent_id") and args.agent_id:
                agents_to_restore = [a for a in backup.agents if a.agent_id == args.agent_id]
                if not agents_to_restore:
                    print(f"Error: Agent '{args.agent_id}' not found in backup", file=sys.stderr)
                    return EXIT_NOT_FOUND

            if not ctx.quiet:
                print("\nBackup information:", file=sys.stderr)
                print(f"  Created: {backup.metadata.date}", file=sys.stderr)
                print(f"  Total agents in backup: {backup.metadata.agent_count}", file=sys.stderr)
                print(f"  Agents to restore: {len(agents_to_restore)}", file=sys.stderr)

            # Dry-run mode
            if hasattr(args, "dry_run") and args.dry_run:
                print("\nDRY RUN - No changes will be made", file=sys.stderr)
                print("\nAgents that would be restored:")
                for agent in agents_to_restore:
                    print(f"  - {agent.agent_id} ({agent.name})")
                    print(f"    Template: {agent.template}")
                    print(f"    Port: {agent.port}")
                    print(f"    Environment vars: {len(agent.environment_vars or {})}")
                return EXIT_SUCCESS

            # Restore agents
            restored = []
            failed = []

            for agent in agents_to_restore:
                try:
                    if ctx.verbose:
                        print(f"\nRestoring agent: {agent.agent_id}", file=sys.stderr)

                    # Check if agent exists
                    try:
                        ctx.client.get_agent(agent.agent_id)
                        if not ctx.quiet:
                            print("  Agent exists, updating configuration...", file=sys.stderr)

                        # Update existing agent
                        update_data = {"environment": agent.environment_vars or {}, "restart": True}
                        ctx.client.update_agent_config(agent.agent_id, update_data)
                        restored.append(agent.agent_id)

                    except Exception as e:
                        # Agent doesn't exist, create it
                        if "404" in str(e) or "not found" in str(e).lower():
                            if not ctx.quiet:
                                print("  Creating new agent...", file=sys.stderr)

                            ctx.client.create_agent(
                                name=agent.name,
                                template=agent.template,
                                environment=agent.environment_vars or {},
                            )
                            restored.append(agent.agent_id)
                        else:
                            raise

                except Exception as e:
                    failed.append(agent.agent_id)
                    if not ctx.quiet:
                        print(f"  Error restoring {agent.agent_id}: {e}", file=sys.stderr)

            # Print summary
            if not ctx.quiet:
                print("\nRestore completed!", file=sys.stderr)
                print(f"  Restored: {len(restored)}", file=sys.stderr)
                print(f"  Failed: {len(failed)}", file=sys.stderr)

            # Output results
            if ctx.output_format == "json":
                result = {
                    "success": len(failed) == 0,
                    "agents_restored": restored,
                    "agents_failed": failed,
                    "total": len(agents_to_restore),
                }
                print(json.dumps(result, indent=2))
            else:
                if restored:
                    print("\nRestored agents:")
                    for agent_id in restored:
                        print(f"  - {agent_id}")
                if failed:
                    print("\nFailed agents:")
                    for agent_id in failed:
                        print(f"  - {agent_id}")

            return EXIT_SUCCESS if len(failed) == 0 else EXIT_ERROR

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return EXIT_API_ERROR
