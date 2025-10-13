#!/usr/bin/env python3
"""Test if Alpine can run bash scripts."""

import sys

sys.path.insert(0, "/opt/ciris-manager")

from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.multi_server_docker import MultiServerDockerClient

config = CIRISManagerConfig.from_file("/etc/ciris-manager/config.yml")
docker_client_manager = MultiServerDockerClient(config.servers)
docker_client = docker_client_manager.get_client("scout")

print("=" * 70)
print(" Testing Alpine Bash Compatibility")
print("=" * 70)

# Test 1: Check if bash exists
print("\n[1] Check if bash exists in Alpine...")
try:
    result = docker_client.containers.run(
        "alpine:latest",
        command="which bash",
        remove=True,
        detach=False,
    )
    print(f"Result: {result.decode()}")
except Exception as e:
    print(f"No bash found: {e}")

# Test 2: Try running the script directly
print("\n[2] Try running script directly (will fail without bash)...")
try:
    result = docker_client.containers.run(
        "alpine:latest",
        command="/home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/test",
        volumes={
            "/home/ciris": {"bind": "/home/ciris", "mode": "ro"},
            "/opt/ciris": {"bind": "/opt/ciris", "mode": "rw"},
        },
        remove=True,
        detach=False,
    )
    print(f"Success: {result.decode()}")
except Exception as e:
    print(f"Failed (expected): {e}")

# Test 3: Try running with explicit bash
print("\n[3] Try running with explicit bash command...")
try:
    result = docker_client.containers.run(
        "alpine:latest",
        command="bash /home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/test",
        volumes={
            "/home/ciris": {"bind": "/home/ciris", "mode": "ro"},
            "/opt/ciris": {"bind": "/opt/ciris", "mode": "rw"},
        },
        remove=True,
        detach=False,
    )
    print(f"Result: {result.decode()}")
except Exception as e:
    print(f"Failed: {e}")

# Test 4: Try running with sh (Alpine's default shell)
print("\n[4] Try running with sh (Alpine's default)...")
try:
    result = docker_client.containers.run(
        "alpine:latest",
        command="sh /home/ciris/shared/fix_agent_permissions.sh /opt/ciris/agents/test",
        volumes={
            "/home/ciris": {"bind": "/home/ciris", "mode": "ro"},
            "/opt/ciris": {"bind": "/opt/ciris", "mode": "rw"},
        },
        remove=True,
        detach=False,
    )
    print(f"Result: {result.decode()}")
except Exception as e:
    print(f"Failed: {e}")

print("\n" + "=" * 70)
