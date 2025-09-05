#!/usr/bin/env python3
"""
Fix permissions for CIRIS agent directories.

This script fixes ownership and permissions for agent directories
to ensure they work with the containerized CIRIS agents.

Usage:
    sudo python3 fix-agent-permissions.py [agent-id]

If no agent-id is provided, it will fix all agents.
"""

import os
import sys
import subprocess
from pathlib import Path


def fix_agent_permissions(agent_path: Path) -> bool:
    """Fix permissions for a single agent directory."""

    if not agent_path.exists():
        print(f"✗ Agent directory does not exist: {agent_path}")
        return False

    agent_id = agent_path.name
    print(f"Fixing permissions for agent: {agent_id}")

    # Define directory permissions
    directories = {
        "data": 0o755,
        "data_archive": 0o755,
        "logs": 0o755,
        "config": 0o755,
        "audit_keys": 0o700,
        ".secrets": 0o700,
    }

    success = True

    for dir_name, permissions in directories.items():
        dir_path = agent_path / dir_name

        if not dir_path.exists():
            print(f"  Creating {dir_name}...")
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"  ✗ Failed to create {dir_name}: {e}")
                success = False
                continue

        try:
            # Set permissions
            os.chmod(dir_path, permissions)
            # Set ownership to uid 1000 (container user)
            os.chown(dir_path, 1000, 1000)
            print(f"  ✓ Fixed {dir_name}: {oct(permissions)} owner=1000:1000")
        except Exception as e:
            print(f"  ✗ Failed to fix {dir_name}: {e}")
            success = False

    # Also fix ownership of the agent directory itself
    try:
        os.chown(agent_path, 1000, 1000)
        print("  ✓ Fixed agent directory ownership")
    except Exception as e:
        print(f"  ✗ Failed to fix agent directory ownership: {e}")
        # This is not critical, don't mark as failure

    return success


def main():
    # Check if running as root
    if os.geteuid() != 0:
        print("Error: This script must be run as root (use sudo)")
        sys.exit(1)

    agents_base = Path("/opt/ciris/agents")

    if not agents_base.exists():
        print(f"Error: Agents directory does not exist: {agents_base}")
        sys.exit(1)

    # Check if specific agent was provided
    if len(sys.argv) > 1:
        agent_id = sys.argv[1]
        agent_path = agents_base / agent_id

        if not agent_path.exists():
            print(f"Error: Agent directory does not exist: {agent_path}")
            print("\nAvailable agents:")
            for agent_dir in agents_base.iterdir():
                if agent_dir.is_dir() and not agent_dir.name.startswith("."):
                    print(f"  - {agent_dir.name}")
            sys.exit(1)

        success = fix_agent_permissions(agent_path)
        if success:
            print(f"\n✅ Successfully fixed permissions for {agent_id}")

            # Check if agent is running and offer to restart
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "ps",
                        "--filter",
                        f"name=ciris-{agent_id}",
                        "--format",
                        "{{.Names}}",
                    ],
                    capture_output=True,
                    text=True,
                )
                if result.stdout.strip():
                    print(f"\nAgent {agent_id} is running. You may need to restart it:")
                    print(f"  cd /opt/ciris/agents/{agent_id} && docker-compose restart")
            except Exception:
                pass
        else:
            print(f"\n✗ Some permissions could not be fixed for {agent_id}")
            sys.exit(1)
    else:
        # Fix all agents
        print("Fixing permissions for all agents...")

        failed_agents = []
        fixed_agents = []

        for agent_dir in agents_base.iterdir():
            if agent_dir.is_dir() and not agent_dir.name.startswith("."):
                if fix_agent_permissions(agent_dir):
                    fixed_agents.append(agent_dir.name)
                else:
                    failed_agents.append(agent_dir.name)
                print()  # Empty line between agents

        # Summary
        if fixed_agents:
            print(f"\n✅ Successfully fixed {len(fixed_agents)} agents:")
            for agent in fixed_agents:
                print(f"  - {agent}")

        if failed_agents:
            print(f"\n✗ Failed to fix {len(failed_agents)} agents:")
            for agent in failed_agents:
                print(f"  - {agent}")
            sys.exit(1)

        if not fixed_agents and not failed_agents:
            print("\nNo agents found to fix.")


if __name__ == "__main__":
    main()
