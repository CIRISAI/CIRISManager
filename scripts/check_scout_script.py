#!/usr/bin/env python3
"""Check if permission script is accessible on scout server."""

import sys

sys.path.insert(0, "/opt/ciris-manager")

from ciris_manager.config.settings import CIRISManagerConfig
from ciris_manager.multi_server_docker import MultiServerDockerClient

config = CIRISManagerConfig.from_file("/etc/ciris-manager/config.yml")
docker_client_manager = MultiServerDockerClient(config.servers)
docker_client = docker_client_manager.get_client("scout")

print("=" * 70)
print(" Checking Permission Script on Scout Server")
print("=" * 70)

# Method 1: Check via nginx container
print("\n[1] Checking via nginx container...")
try:
    nginx_container = docker_client.containers.get("ciris-nginx")
    exec_result = nginx_container.exec_run("ls -la /home/ciris/shared/", user="root")
    print(f"Exit code: {exec_result.exit_code}")
    print(f"Output:\n{exec_result.output.decode()}")
except Exception as e:
    print(f"Failed: {e}")

# Method 2: Check via Alpine with volume mount
print("\n[2] Checking via Alpine container with /home/ciris mount...")
try:
    result = docker_client.containers.run(
        "alpine:latest",
        command="ls -la /home/ciris/shared/",
        volumes={"/home/ciris": {"bind": "/home/ciris", "mode": "ro"}},
        remove=True,
        detach=False,
    )
    print(f"Output:\n{result.decode()}")
except Exception as e:
    print(f"Failed: {e}")

# Method 3: Check if /home/ciris exists on host
print("\n[3] Checking if /home/ciris exists on scout host...")
try:
    result = docker_client.containers.run(
        "alpine:latest",
        command="ls -la /host-home/",
        volumes={"/home": {"bind": "/host-home", "mode": "ro"}},
        remove=True,
        detach=False,
    )
    print(f"Output:\n{result.decode()}")
except Exception as e:
    print(f"Failed: {e}")

print("\n" + "=" * 70)
