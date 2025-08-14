"""
CLI commands for service token management.
"""

import asyncio
import json
from pathlib import Path

from ciris_manager.agent_registry import AgentRegistry
from ciris_manager.token_manager import TokenManager, TokenStatus


def handle_token_list(args):
    """Handle token list command."""

    async def _list():
        registry = AgentRegistry(Path("/opt/ciris/agents/metadata.json"))
        manager = TokenManager(registry)

        print("Checking token health...")
        token_health = await manager.list_tokens()

        if getattr(args, "json", False):
            output = []
            for health in token_health:
                output.append(
                    {
                        "agent_id": health.agent_id,
                        "status": health.status.value,
                        "error": health.error_message,
                    }
                )
            print(json.dumps(output, indent=2))
        else:
            print("\nAgent Token Status")
            print("-" * 60)
            for health in token_health:
                status_marker = "✓" if health.status == TokenStatus.VALID else "✗"
                print(
                    f"{status_marker} {health.agent_id:20} {health.status.value:15} {health.error_message or ''}"
                )

    asyncio.run(_list())
    return 0


def handle_token_verify(args):
    """Handle token verify command."""

    async def _verify():
        registry = AgentRegistry(Path("/opt/ciris/agents/metadata.json"))
        manager = TokenManager(registry)

        print(f"Verifying token for {args.agent_id}...")
        success, message = await manager.verify_token(args.agent_id)

        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"agent_id": args.agent_id, "success": success, "message": message}, indent=2
                )
            )
        else:
            if success:
                print(f"✓ {message}")
                return 0
            else:
                print(f"✗ {message}")
                return 1

    return asyncio.run(_verify())


def handle_token_regenerate(args):
    """Handle token regenerate command."""
    if not args.force:
        response = input(
            f"Are you sure you want to regenerate the token for {args.agent_id}? (y/N): "
        )
        if response.lower() != "y":
            print("Aborted")
            return 0

    async def _regenerate():
        registry = AgentRegistry(Path("/opt/ciris/agents/metadata.json"))
        manager = TokenManager(registry)

        # Backup metadata first
        print("Creating metadata backup...")
        try:
            backup_path = manager.backup_metadata()
            print(f"✓ Backup created: {backup_path}")
        except Exception as e:
            print(f"Failed to create backup: {e}")
            return 1

        print(f"Regenerating token for {args.agent_id}...")
        result = await manager.regenerate_token(
            args.agent_id, restart_container=not args.no_restart
        )

        if result.success:
            print(f"✓ Token regenerated successfully for {args.agent_id}")
            if result.old_token_backed_up:
                print("  • Old token backed up")
            if result.container_restarted:
                print("  • Container restarted")
            if result.auth_verified:
                print("  • Authentication verified")
            return 0
        else:
            print(f"✗ Failed to regenerate token for {args.agent_id}")
            if result.error_message:
                print(f"  {result.error_message}")
            return 1

    return asyncio.run(_regenerate())


def handle_token_rotate(args):
    """Handle token rotate command."""
    if not args.force:
        response = input(
            f"Are you sure you want to rotate ALL agent tokens using {args.strategy} strategy? (y/N): "
        )
        if response.lower() != "y":
            print("Aborted")
            return 0

    async def _rotate():
        registry = AgentRegistry(Path("/opt/ciris/agents/metadata.json"))
        manager = TokenManager(registry)

        # Backup metadata first
        print("Creating metadata backup...")
        try:
            backup_path = manager.backup_metadata()
            print(f"✓ Backup created: {backup_path}")
        except Exception as e:
            print(f"Failed to create backup: {e}")
            return 1

        print("Rotating tokens...")
        results = await manager.rotate_all_tokens(
            strategy=args.strategy, canary_percentage=args.canary_percentage
        )

        # Display results
        success_count = sum(1 for r in results.values() if r.success)
        total_count = len(results)

        if success_count == total_count:
            print(f"✓ Successfully rotated tokens for all {total_count} agents")
            return 0
        else:
            print(f"⚠ Rotated {success_count}/{total_count} agent tokens")

            # Show failures
            for agent_id, result in results.items():
                if not result.success:
                    print(f"  ✗ {agent_id}: {result.error_message}")

            if success_count < total_count:
                print("\nTo restore from backup:")
                print(f"  ciris-manager tokens restore {backup_path}")
            return 1

    return asyncio.run(_rotate())


def handle_token_recover(args):
    """Handle token recover command."""

    async def _recover():
        registry = AgentRegistry(Path("/opt/ciris/agents/metadata.json"))
        manager = TokenManager(registry)

        if not args.dry_run:
            # Backup metadata first
            print("Creating metadata backup...")
            try:
                backup_path = manager.backup_metadata()
                print(f"✓ Backup created: {backup_path}")
            except Exception as e:
                print(f"Failed to create backup: {e}")
                return 1

        print("Recovering tokens from containers...")

        if args.dry_run:
            # Just list what would be done
            agents = registry.list_agents()
            print("\nDRY RUN - Would recover tokens for:")
            for agent in agents:
                print(f"  • {agent.agent_id}")
            return 0
        else:
            results = await manager.recover_tokens_from_containers()

            success_count = sum(1 for success in results.values() if success)
            total_count = len(results)

            if success_count == total_count:
                print(f"✓ Successfully recovered tokens for all {total_count} agents")
                return 0
            else:
                print(f"⚠ Recovered {success_count}/{total_count} agent tokens")

                # Show failures
                for agent_id, success in results.items():
                    if not success:
                        print(f"  ✗ Failed to recover token for {agent_id}")
                return 1

    return asyncio.run(_recover())


def handle_token_validate(args):
    """Handle token validate command."""

    async def _validate():
        registry = AgentRegistry(Path("/opt/ciris/agents/metadata.json"))
        manager = TokenManager(registry)

        print("Validating all tokens...")
        results = await manager.validate_all_tokens()

        if getattr(args, "json", False):
            output = {}
            for agent_id, health in results.items():
                output[agent_id] = {
                    "status": health.status.value,
                    "auth_tested": health.auth_tested,
                    "auth_successful": health.auth_successful,
                    "error": health.error_message,
                }
            print(json.dumps(output, indent=2))
        else:
            print("\nToken Validation Results")
            print("-" * 80)
            print(f"{'Agent ID':20} {'Token Status':15} {'Auth Test':15} {'Error':30}")
            print("-" * 80)

            all_valid = True
            for agent_id, health in results.items():
                auth_result = ""
                if health.auth_tested:
                    if health.auth_successful:
                        auth_result = "✓ Passed"
                    else:
                        auth_result = "✗ Failed"
                        all_valid = False
                else:
                    auth_result = "Not tested"
                    if health.status == TokenStatus.VALID:
                        all_valid = False

                status_marker = "✓" if health.status == TokenStatus.VALID else "✗"
                print(
                    f"{agent_id:20} {status_marker} {health.status.value:13} {auth_result:15} {health.error_message or ''}"
                )

            print("-" * 80)
            if all_valid:
                print("\n✓ All tokens are valid and authenticated")
                return 0
            else:
                print("\n⚠ Some tokens have issues")
                return 1

    return asyncio.run(_validate())


def handle_token_restore(args):
    """Handle token restore command."""
    backup = Path(args.backup_path)

    if not args.force:
        response = input(f"Are you sure you want to restore metadata from {backup}? (y/N): ")
        if response.lower() != "y":
            print("Aborted")
            return 0

    registry = AgentRegistry(Path("/opt/ciris/agents/metadata.json"))
    manager = TokenManager(registry)

    if manager.restore_metadata(backup):
        print(f"✓ Successfully restored metadata from {backup}")
        print("Note: You may need to restart agents for changes to take effect")
        return 0
    else:
        print(f"✗ Failed to restore metadata from {backup}")
        return 1
